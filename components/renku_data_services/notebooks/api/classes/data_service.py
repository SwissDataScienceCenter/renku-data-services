"""Helpers for interacting wit the data service."""

from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx

from renku_data_services.base_models import APIUser
from renku_data_services.crc.db import ResourcePoolRepository
from renku_data_services.crc.models import ResourceClass, ResourcePool
from renku_data_services.notebooks.api.classes.repository import (
    INTERNAL_GITLAB_PROVIDER,
    GitProvider,
    OAuth2Connection,
    OAuth2Provider,
)
from renku_data_services.notebooks.api.schemas.server_options import ServerOptions
from renku_data_services.notebooks.errors.intermittent import IntermittentError
from renku_data_services.notebooks.errors.user import InvalidComputeResourceError


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


@dataclass
class GitProviderHelper:
    """Calls to the data service to configure git providers."""

    service_url: str
    renku_url: str
    internal_gitlab_url: str
    enable_internal_gitlab: bool

    def __post_init__(self) -> None:
        self.service_url = self.service_url.rstrip("/")
        self.renku_url = self.renku_url.rstrip("/")

    async def get_providers(self, user: APIUser) -> list[GitProvider]:
        """Get the providers for the specific user."""
        if user is None or user.access_token is None:
            return []
        connections = await self.get_oauth2_connections(user=user)
        providers: dict[str, GitProvider] = dict()
        for c in connections:
            if c.provider_id in providers:
                continue
            provider = await self.get_oauth2_provider(c.provider_id)
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

    async def get_oauth2_connections(self, user: APIUser | None = None) -> list[OAuth2Connection]:
        """Get oauth2 connections."""
        if user is None or user.access_token is None:
            return []
        request_url = f"{self.service_url}/oauth2/connections"
        headers = {"Authorization": f"bearer {user.access_token}"}
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(request_url, headers=headers)
        if res.status_code != 200:
            raise IntermittentError(message="The data service sent an unexpected response, please try again later")
        connections = res.json()
        connections = [OAuth2Connection.from_dict(c) for c in connections if c["status"] == "connected"]
        return connections

    async def get_oauth2_provider(self, provider_id: str) -> OAuth2Provider:
        """Get a specific provider."""
        request_url = f"{self.service_url}/oauth2/providers/{provider_id}"
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(request_url)
        if res.status_code != 200:
            raise IntermittentError(message="The data service sent an unexpected response, please try again later")
        provider = res.json()
        return OAuth2Provider.from_dict(provider)


@dataclass
class DummyGitProviderHelper:
    """Helper for git providers."""

    async def get_providers(self, user: APIUser) -> list[GitProvider]:
        """Get a list of providers."""
        return []
