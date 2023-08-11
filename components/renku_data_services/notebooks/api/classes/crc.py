from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests

from ...errors.intermittent import IntermittentError
from ...errors.programming import ConfigurationError
from ...errors.user import InvalidComputeResourceError
from ..schemas.server_options import ServerOptions
from .user import User


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
        Storage in memory are assumed to be in gigabytes."""
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
            raise InvalidComputeResourceError(
                message=f"The resource class ID {class_id} does not exist."
            )
        if storage is None:
            storage = res_class.get("default_storage", 1)
        if storage < 1:
            raise InvalidComputeResourceError(
                message="Storage requests have to be greater than or equal to 1GB."
            )
        if storage > res_class.get("max_storage"):
            raise InvalidComputeResourceError(
                message="The requested storage surpasses the maximum value allowed."
            )
        options = ServerOptions.from_resource_class(res_class)
        options.set_storage(storage, gigabytes=True)
        quota = pool.get("quota")
        if quota is not None and isinstance(quota, dict):
            options.priority_class = quota.get("id")
        return options

    def get_default_class(self) -> Dict[str, Any]:
        pools = self._get_resource_pools()
        default_pools = [p for p in pools if p.get("default", False)]
        if len(default_pools) < 1:
            raise ConfigurationError("Cannot find the default resource pool.")
        default_pool = default_pools[0]
        default_classes = [
            cls for cls in default_pool.get("classes", []) if cls.get("default", False)
        ]
        if len(default_classes) < 1:
            raise ConfigurationError("Cannot find the default resource class.")
        return default_classes[0]

    def find_acceptable_class(
        self, user: User, requested_server_options: ServerOptions
    ) -> Optional[ServerOptions]:
        """Find a resource class that is available to the user that is greater than or equal to
        the old-style server options that the user requested."""
        resource_pools = self._get_resource_pools(
            user=user, server_options=requested_server_options
        )
        # Difference and best candidate in the case that the resource class will be
        # greater than or equal to the request
        best_larger_or_equal_diff = None
        best_larger_or_equal_class = None
        zero_diff = ServerOptions(
            cpu=0, memory=0, gpu=0, storage=0, priority_class=resource_pools
        )
        for resource_pool in resource_pools:
            quota = resource_pool.get("quota")
            for resource_class in resource_pool["classes"]:
                resource_class_mdl = ServerOptions.from_resource_class(resource_class)
                if quota is not None and isinstance(quota, dict):
                    resource_class_mdl.priority_class = quota.get("id")
                diff = resource_class_mdl - requested_server_options
                if (
                    diff >= zero_diff
                    and (
                        best_larger_or_equal_diff is None
                        or diff < best_larger_or_equal_diff
                    )
                    and resource_class["matching"]
                ):
                    best_larger_or_equal_diff = diff
                    best_larger_or_equal_class = resource_class_mdl
        return best_larger_or_equal_class

    def _get_resource_pools(
        self,
        user: Optional[User] = None,
        server_options: Optional[ServerOptions] = None,
    ) -> List[Dict[str, Any]]:
        headers = None
        params = None
        if user is not None and user.access_token is not None:
            headers = {"Authorization": f"bearer {user.access_token}"}
        if server_options is not None:
            params = {
                "cpu": server_options.cpu,
                "gpu": server_options.gpu,
                "memory": server_options.memory
                if server_options.gigabytes
                else round(server_options.memory / 1_000_000_000),
                "max_storage": server_options.storage
                if server_options.gigabytes
                else round(server_options.storage / 1_000_000_000),
            }
        res = requests.get(
            self.crc_url + "/resource_pools", headers=headers, params=params
        )
        if res.status_code != 200:
            raise IntermittentError(
                message="The compute resource access control service sent "
                "an unexpected response, please try again later",
            )
        return res.json()


@dataclass
class DummyCRCValidator:
    options: ServerOptions = field(
        default_factory=lambda: ServerOptions(0.5, 1, 0, 1, "/lab", False, True)
    )

    def validate_class_storage(self, *args, **kwargs) -> ServerOptions:
        return self.options

    def get_default_class(self) -> Dict[str, Any]:
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
