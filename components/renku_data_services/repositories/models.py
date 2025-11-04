"""Models for connected services."""

from dataclasses import dataclass

from ulid import ULID


@dataclass(frozen=True, eq=True, kw_only=True)
class RepositoryPermissions:
    """Repository permissions for git operations."""

    pull: bool
    push: bool

    @classmethod
    def default(cls) -> "RepositoryPermissions":
        """Default permissions."""
        return cls(pull=False, push=False)


@dataclass(frozen=True, eq=True, kw_only=True)
class RepositoryMetadata:
    """Repository metadata."""

    etag: str | None
    git_http_url: str
    web_url: str
    permissions: RepositoryPermissions


@dataclass(frozen=True, eq=True, kw_only=True)
class RepositoryProviderMatch:
    """Repository provider match data."""

    provider_id: str
    connection_id: ULID | None
    repository_metadata: RepositoryMetadata | None


@dataclass(frozen=True, eq=True, kw_only=True)
class ProviderConnection:
    """Repository connection data."""

    id: ULID
    provider_id: str
    status: str


@dataclass(frozen=True, eq=True, kw_only=True)
class ProviderData:
    """Repository provider data."""

    id: str
    name: str
    url: str


@dataclass(frozen=True, eq=True, kw_only=True)
class RepositoryProviderData:
    """Repository provider match data."""

    provider: ProviderData
    connection: ProviderConnection | None
    repository_metadata: RepositoryMetadata | None
