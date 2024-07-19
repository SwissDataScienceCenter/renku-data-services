"""Models for query parameters."""

from pydantic import Field

from renku_data_services.namespace.apispec import GroupRole
from renku_data_services.namespace.apispec_base import BaseAPISpec


class GetNamespacesParams(BaseAPISpec):
    """The schema for the query parameters used in the get namespaces request."""

    class Config:
        """Configuration."""

        extra = "ignore"

    minimum_role: GroupRole | None = Field(default=None)
