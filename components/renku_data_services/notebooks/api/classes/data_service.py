from dataclasses import dataclass, field
from typing import Any, NamedTuple, Optional
from urllib.parse import urljoin, urlparse

import requests
from flask import current_app

from renku_notebooks.errors.intermittent import IntermittentError
from renku_notebooks.errors.programming import ConfigurationError
from renku_notebooks.errors.user import (
    AuthenticationError,
    InvalidCloudStorageConfiguration,
    InvalidComputeResourceError,
    MissingResourceError,
)

from ..schemas.server_options import ServerOptions
from .repository import INTERNAL_GITLAB_PROVIDER, GitProvider, OAuth2Connection, OAuth2Provider
from .user import User


class CloudStorageConfig(NamedTuple):
    config: dict[str, Any]
    source_path: str
    target_path: str
    readonly: bool
    name: str


@dataclass
class StorageValidator:
    storage_url: str

    def __post_init__(self):
        self.storage_url = self.storage_url.rstrip("/")

    def get_storage_by_id(self, user: User, project_id: int, storage_id: str) -> CloudStorageConfig:
        headers = None
        if user is not None and user.access_token is not None and user.git_token is not None:
            headers = {
                "Authorization": f"bearer {user.access_token}",
                "Gitlab-Access-Token": user.git_token,
            }
        # TODO: remove project_id once authz on the data service works properly
        request_url = self.storage_url + f"/storage/{storage_id}?project_id={project_id}"
        current_app.logger.info(f"getting storage info by id: {request_url}")
        res = requests.get(request_url, headers=headers)
        if res.status_code == 404:
            raise MissingResourceError(message=f"Couldn't find cloud storage with id {storage_id}")
        if res.status_code == 401:
            raise AuthenticationError("User is not authorized to access this storage on this project.")
        if res.status_code != 200:
            raise IntermittentError(
                message="The data service sent an unexpected response, please try again later",
            )
        storage = res.json()["storage"]
        return CloudStorageConfig(
            config=storage["configuration"],
            source_path=storage["source_path"],
            target_path=storage["target_path"],
            readonly=storage.get("readonly", True),
            name=storage["name"],
        )

    def validate_storage_configuration(self, configuration: dict[str, Any], source_path: str) -> None:
        res = requests.post(self.storage_url + "/storage_schema/validate", json=configuration)
        if res.status_code == 422:
            raise InvalidCloudStorageConfiguration(
                message=f"The provided cloud storage configuration isn't valid: {res.json()}",
            )
        if res.status_code != 204:
            raise IntermittentError(
                message="The data service sent an unexpected response, please try again later",
            )

    def obscure_password_fields_for_storage(self, configuration: dict[str, Any]) -> dict[str, Any]:
        """Obscures password fields for use with rclone."""
        res = requests.post(self.storage_url + "/storage_schema/obscure", json=configuration)

        if res.status_code != 200:
            raise InvalidCloudStorageConfiguration(
                message=f"Couldn't obscure password fields for configuration: {res.json()}"
            )

        return res.json()


@dataclass
class DummyStorageValidator:
    def get_storage_by_id(self, user: User, project_id: int, storage_id: str) -> CloudStorageConfig:
        raise NotImplementedError()

    def validate_storage_configuration(self, configuration: dict[str, Any], source_path: str) -> None:
        raise NotImplementedError()


@dataclass
class CRCValidator:
    """Calls to the CRC service to validate resource requests."""

    crc_url: str

    def __post_init__(self):
        self.crc_url = self.crc_url.rstrip("/")

    def validate_class_storage(
        self,
        user: User,
        class_id: int,
        storage: Optional[int] = None,
    ) -> ServerOptions:
        """Ensures that the resource class and storage requested is valid.

        Storage in memory are assumed to be in gigabytes.
        """
        resource_pools = self._get_resource_pools(user=user)
        pool = None
        res_class = None
        for rp in resource_pools:
            for cls in rp["classes"]:
                if cls["id"] == class_id:
                    res_class = cls
                    pool = rp
                    break
        if res_class is None:
            raise InvalidComputeResourceError(message=f"The resource class ID {class_id} does not exist.")
        if storage is None:
            storage = res_class.get("default_storage", 1)
        if storage < 1:
            raise InvalidComputeResourceError(message="Storage requests have to be greater than or equal to 1GB.")
        if storage > res_class.get("max_storage"):
            raise InvalidComputeResourceError(message="The requested storage surpasses the maximum value allowed.")
        options = ServerOptions.from_resource_class(res_class)
        options.idle_threshold_seconds = pool.get("idle_threshold")
        options.hibernation_threshold_seconds = pool.get("hibernation_threshold")
        options.set_storage(storage, gigabytes=True)
        quota = pool.get("quota")
        if quota is not None and isinstance(quota, dict):
            options.priority_class = quota.get("id")
        return options

    def get_default_class(self) -> dict[str, Any]:
        pools = self._get_resource_pools()
        default_pools = [p for p in pools if p.get("default", False)]
        if len(default_pools) < 1:
            raise ConfigurationError("Cannot find the default resource pool.")
        default_pool = default_pools[0]
        default_classes = [cls for cls in default_pool.get("classes", []) if cls.get("default", False)]
        if len(default_classes) < 1:
            raise ConfigurationError("Cannot find the default resource class.")
        return default_classes[0]

    def find_acceptable_class(self, user: User, requested_server_options: ServerOptions) -> Optional[ServerOptions]:
        """Find a resource class greater than or equal to the old-style server options being requested.

        Only classes available to the user are considered.
        """
        resource_pools = self._get_resource_pools(user=user, server_options=requested_server_options)
        # Difference and best candidate in the case that the resource class will be
        # greater than or equal to the request
        best_larger_or_equal_diff = None
        best_larger_or_equal_class = None
        zero_diff = ServerOptions(cpu=0, memory=0, gpu=0, storage=0, priority_class=resource_pools)
        for resource_pool in resource_pools:
            quota = resource_pool.get("quota")
            for resource_class in resource_pool["classes"]:
                resource_class_mdl = ServerOptions.from_resource_class(resource_class)
                if quota is not None and isinstance(quota, dict):
                    resource_class_mdl.priority_class = quota.get("id")
                diff = resource_class_mdl - requested_server_options
                if (
                    diff >= zero_diff
                    and (best_larger_or_equal_diff is None or diff < best_larger_or_equal_diff)
                    and resource_class["matching"]
                ):
                    best_larger_or_equal_diff = diff
                    best_larger_or_equal_class = resource_class_mdl
        return best_larger_or_equal_class

    def _get_resource_pools(
        self,
        user: Optional[User] = None,
        server_options: Optional[ServerOptions] = None,
    ) -> list[dict[str, Any]]:
        headers = None
        params = None
        if user is not None and user.access_token is not None:
            headers = {"Authorization": f"bearer {user.access_token}"}
        if server_options is not None:
            params = {
                "cpu": server_options.cpu,
                "gpu": server_options.gpu,
                "memory": (
                    server_options.memory if server_options.gigabytes else round(server_options.memory / 1_000_000_000)
                ),
                "max_storage": (
                    server_options.storage
                    if server_options.gigabytes
                    else round(server_options.storage / 1_000_000_000)
                ),
            }
        res = requests.get(self.crc_url + "/resource_pools", headers=headers, params=params)
        if res.status_code != 200:
            raise IntermittentError(
                message="The compute resource access control service sent "
                "an unexpected response, please try again later",
            )
        return res.json()


@dataclass
class DummyCRCValidator:
    options: ServerOptions = field(default_factory=lambda: ServerOptions(0.5, 1, 0, 1, "/lab", False, True))

    def validate_class_storage(self, *args, **kwargs) -> ServerOptions:
        return self.options

    def get_default_class(self) -> dict[str, Any]:
        return {
            "name": "resource class",
            "cpu": 0.1,
            "memory": 1,
            "gpu": 0,
            "max_storage": 100,
            "default_storage": 1,
            "id": 1,
            "default": True,
        }

    def find_acceptable_class(self, *args, **kwargs) -> Optional[ServerOptions]:
        return self.options


@dataclass
class GitProviderHelper:
    """Calls to the data service to configure git providers."""

    service_url: str
    renku_url: str
    internal_gitlab_url: str

    def __post_init__(self):
        self.service_url = self.service_url.rstrip("/")
        self.renku_url = self.renku_url.rstrip("/")

    def get_providers(self, user: User) -> list[GitProvider]:
        if user is None or user.access_token is None:
            return []
        connections = self.get_oauth2_connections(user=user)
        providers: dict[str, GitProvider] = dict()
        for c in connections:
            if c.provider_id in providers:
                continue
            provider = self.get_oauth2_provider(c.provider_id)
            access_token_url = urljoin(
                self.renku_url,
                urlparse(f"{self.service_url}/oauth2/connections/{c.id}/token").path,
            )
            providers[c.provider_id] = GitProvider(
                id=c.provider_id,
                url=provider.url,
                connection_id=c.id,
                access_token_url=access_token_url,
            )

        providers_list = list(providers.values())
        # Insert the internal GitLab as the first provider
        internal_gitlab_access_token_url = urljoin(
            self.renku_url, "/api/auth/gitlab/exchange"
        )
        providers_list.insert(
            0,
            GitProvider(
                id=INTERNAL_GITLAB_PROVIDER,
                url=self.internal_gitlab_url,
                connection_id="",
                access_token_url=internal_gitlab_access_token_url,
            ),
        )
        return providers_list

    def get_oauth2_connections(
        self, user: User | None = None
    ) -> list[OAuth2Connection]:
        if user is None or user.access_token is None:
            return []
        request_url = f"{self.service_url}/oauth2/connections"
        headers = {"Authorization": f"bearer {user.access_token}"}
        res = requests.get(request_url, headers=headers)
        if res.status_code != 200:
            raise IntermittentError(
                message="The data service sent an unexpected response, please try again later"
            )
        connections = res.json()
        connections = [
            OAuth2Connection.from_dict(c)
            for c in connections
            if c["status"] == "connected"
        ]
        return connections

    def get_oauth2_provider(self, provider_id: str) -> OAuth2Provider:
        request_url = f"{self.service_url}/oauth2/providers/{provider_id}"
        res = requests.get(request_url)
        if res.status_code != 200:
            raise IntermittentError(
                message="The data service sent an unexpected response, please try again later"
            )
        provider = res.json()
        return OAuth2Provider.from_dict(provider)


@dataclass
class DummyGitProviderHelper:
    def get_providers(self, *args, **kwargs) -> list[GitProvider]:
        return []
