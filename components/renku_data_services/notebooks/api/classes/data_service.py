"""Helpers for interacting wit the data service."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse

from renku_data_services.app_config import logging
from renku_data_services.base_models import APIUser
from renku_data_services.connected_services.db import ConnectedServicesRepository
from renku_data_services.connected_services.utils import GitHubProviderType, get_github_provider_type
from renku_data_services.crc.db import ResourcePoolRepository
from renku_data_services.crc.models import ResourceClass, ResourcePool
from renku_data_services.notebooks.api.classes.repository import (
    INTERNAL_GITLAB_PROVIDER,
    GitProvider,
)
from renku_data_services.notebooks.api.schemas.server_options import ServerOptions
from renku_data_services.notebooks.config.dynamic import _GitConfig, _SessionConfig
from renku_data_services.notebooks.errors.user import InvalidComputeResourceError

logger = logging.getLogger(__name__)


@dataclass
class CRCValidator:
    """Calls to the CRC service to validate resource requests."""

    rp_repo: ResourcePoolRepository

    async def validate_class_storage(
        self,
        user: APIUser,
        class_id: int,
        storage: Optional[int] = None,
    ) -> ServerOptions:
        """Ensures that the resource class and storage requested is valid.

        Storage in memory are assumed to be in gigabytes.
        """
        resource_pools = await self.rp_repo.get_resource_pools(user)
        pool: ResourcePool | None = None
        res_class: ResourceClass | None = None
        for rp in resource_pools:
            for cls in rp.classes:
                if cls.id == class_id:
                    res_class = cls
                    pool = rp
                    break
        if pool is None or res_class is None:
            raise InvalidComputeResourceError(message=f"The resource class ID {class_id} does not exist.")
        if storage is None:
            storage = res_class.default_storage
        if storage < 1:
            raise InvalidComputeResourceError(message="Storage requests have to be greater than or equal to 1GB.")
        if storage > res_class.max_storage:
            raise InvalidComputeResourceError(message="The requested storage surpasses the maximum value allowed.")
        options = ServerOptions.from_resource_class(res_class)
        options.idle_threshold_seconds = pool.idle_threshold
        options.hibernation_threshold_seconds = pool.hibernation_threshold
        options.set_storage(storage, gigabytes=True)
        quota = pool.quota
        if quota is not None:
            options.priority_class = quota.id
        return options

    async def get_default_class(self) -> ResourceClass:
        """Get the default resource class from the default resource pool."""
        return await self.rp_repo.get_default_resource_class()

    async def find_acceptable_class(
        self, user: APIUser, requested_server_options: ServerOptions
    ) -> Optional[ServerOptions]:
        """Find a resource class greater than or equal to the old-style server options being requested.

        Only classes available to the user are considered.
        """
        resource_pools = await self._get_resource_pools(user=user, server_options=requested_server_options)
        # Difference and best candidate in the case that the resource class will be
        # greater than or equal to the request
        best_larger_or_equal_diff: ServerOptions | None = None
        best_larger_or_equal_class: ServerOptions | None = None
        zero_diff = ServerOptions(cpu=0, memory=0, gpu=0, storage=0)
        for resource_pool in resource_pools:
            quota = resource_pool.quota
            for resource_class in resource_pool.classes:
                resource_class_mdl = ServerOptions.from_resource_class(resource_class)
                if quota is not None:
                    resource_class_mdl.priority_class = quota.id
                diff = resource_class_mdl - requested_server_options
                if (
                    diff >= zero_diff
                    and (best_larger_or_equal_diff is None or diff < best_larger_or_equal_diff)
                    and resource_class.matching
                ):
                    best_larger_or_equal_diff = diff
                    best_larger_or_equal_class = resource_class_mdl
        return best_larger_or_equal_class

    async def _get_resource_pools(
        self,
        user: APIUser,
        server_options: Optional[ServerOptions] = None,
    ) -> list[ResourcePool]:
        output: list[ResourcePool] = []
        if server_options is not None:
            options_gb = server_options.to_gigabytes()
            output = await self.rp_repo.filter_resource_pools(
                user,
                cpu=options_gb.cpu,
                memory=round(options_gb.memory),
                max_storage=round(options_gb.storage or 1),
                gpu=options_gb.gpu,
            )
        else:
            output = await self.rp_repo.filter_resource_pools(user)
        return output


@dataclass
class DummyCRCValidator:
    """Dummy validator for resource pools and classes."""

    options: ServerOptions = field(default_factory=lambda: ServerOptions(0.5, 1, 0, 1, "/lab", False, True))

    async def validate_class_storage(self, user: APIUser, class_id: int, storage: int | None = None) -> ServerOptions:
        """Validate the storage against the resource class."""
        return self.options

    async def get_default_class(self) -> ResourceClass:
        """Get the default resource class."""
        return ResourceClass(
            name="resource class",
            cpu=0.1,
            memory=1,
            max_storage=100,
            gpu=0,
            id=1,
            default_storage=1,
            default=True,
        )

    async def find_acceptable_class(
        self, user: APIUser, requested_server_options: ServerOptions
    ) -> Optional[ServerOptions]:
        """Find an acceptable resource class based on the required options."""
        return self.options


class GitProviderHelper:
    """Gets the list of providers."""

    def __init__(
        self,
        connected_services_repo: ConnectedServicesRepository,
        service_url: str,
        renku_url: str,
        internal_gitlab_url: str,
        enable_internal_gitlab: bool,
    ) -> None:
        self.connected_services_repo = connected_services_repo
        self.renku_url = renku_url.rstrip("/")
        self.service_url = service_url.rstrip("/")
        self.internal_gitlab_url: str = internal_gitlab_url
        self.enable_internal_gitlab: bool = enable_internal_gitlab

    async def get_providers(self, user: APIUser) -> list[GitProvider]:
        """Get the providers for the specific user."""
        if user is None or user.access_token is None:
            return []

        logger.debug(f"Get git providers for user {user.id}")

        connections = await self.connected_services_repo.get_oauth2_connections(user)
        providers: dict[str, GitProvider] = dict()
        for c in connections:
            if c.provider_id in providers:
                continue
            provider = await self.connected_services_repo.get_oauth2_client(c.provider_id, user)
            if get_github_provider_type(provider) == GitHubProviderType.oauth_app:
                continue
            access_token_url = urljoin(
                self.renku_url,
                urlparse(f"{self.service_url}/oauth2/connections/{c.id}/token").path,
            )
            providers[c.provider_id] = GitProvider(
                id=c.provider_id, url=provider.url, connection_id=str(c.id), access_token_url=access_token_url
            )

        providers_list = list(providers.values())
        # Insert the internal GitLab as the first provider
        if self.enable_internal_gitlab and self.internal_gitlab_url:
            internal_gitlab_access_token_url = urljoin(self.renku_url, "/api/auth/gitlab/exchange")
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

    @classmethod
    def create(cls, csr: ConnectedServicesRepository, enable_internal_gitlab: bool) -> GitProviderHelper:
        """Create an instance."""
        sessions_config = _SessionConfig.from_env()
        git_config = _GitConfig.from_env(enable_internal_gitlab=enable_internal_gitlab)
        data_service_url = os.environ.get("NB_DATA_SERVICE_URL", "http://127.0.0.1:8000")
        return GitProviderHelper(
            connected_services_repo=csr,
            service_url=data_service_url,
            renku_url=f"http://{sessions_config.ingress.host}",
            internal_gitlab_url=git_config.url,
            enable_internal_gitlab=enable_internal_gitlab,
        )


@dataclass
class DummyGitProviderHelper:
    """Helper for git providers."""

    async def get_providers(self, user: APIUser) -> list[GitProvider]:
        """Get a list of providers."""
        return []
