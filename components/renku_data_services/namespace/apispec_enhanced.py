"""Modified data classes for the apispec."""

from typing import Any

from pydantic import field_validator

from renku_data_services.namespace.apispec import GroupsGetParametersQuery as _GroupsGetParametersQuery
from renku_data_services.namespace.apispec import NamespacesGetParametersQuery as _NamespacesGetParametersQuery


class NamespacesGetParametersQuery(_NamespacesGetParametersQuery):
    """The query parameters for listing namespaces."""

    class Config(_NamespacesGetParametersQuery.Config):
        """Pydantic configuration."""

        extra = "forbid"

    @field_validator("kinds", mode="before")
    @classmethod
    def _convert_to_kinds_to_list(cls, value: Any) -> list[str]:
        if isinstance(value, list):
            return value
        return [str(value)]


class GroupsGetParametersQuery(_GroupsGetParametersQuery):
    """The query parameters for listing groups."""

    class Config(_GroupsGetParametersQuery.Config):
        """Pydantic configuration."""

        extra = "forbid"
