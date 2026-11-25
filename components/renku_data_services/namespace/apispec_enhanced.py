"""Modified data classes for the apispec."""

from typing import Any

from pydantic import ConfigDict, field_validator

from renku_data_services.namespace.apispec import GroupsGetParametersQuery as _GroupsGetParametersQuery
from renku_data_services.namespace.apispec import NamespacesGetParametersQuery as _NamespacesGetParametersQuery


class NamespacesGetParametersQuery(_NamespacesGetParametersQuery):
    """The query parameters for listing namespaces."""

    model_config = ConfigDict(extra="forbid") | _NamespacesGetParametersQuery.model_config

    @field_validator("kinds", mode="before")
    @classmethod
    def _convert_to_kinds_to_list(cls, value: Any) -> list[str]:
        if isinstance(value, list):
            return value
        return [str(value)]


class GroupsGetParametersQuery(_GroupsGetParametersQuery):
    """The query parameters for listing groups."""

    model_config = ConfigDict(extra="forbid") | _GroupsGetParametersQuery.model_config
