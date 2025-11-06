"""Models for connected services."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from ulid import ULID

from renku_data_services.connected_services.orm import OAuth2ClientORM, OAuth2ConnectionORM
from renku_data_services.repositories.git_url import GitUrlError


@dataclass(frozen=True, eq=True, kw_only=True)
class RepositoryPermissions:
    """Repository permissions for git operations."""

    pull: bool
    push: bool

    @classmethod
    def default(cls) -> RepositoryPermissions:
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

    @classmethod
    def fromORM(cls, e: OAuth2ConnectionORM) -> ProviderConnection:
        """Create a ProviderConnection from an ORM class."""
        return ProviderConnection(id=e.id, provider_id=e.client_id, status=e.status)


@dataclass(frozen=True, eq=True, kw_only=True)
class ProviderData:
    """Repository provider data."""

    id: str
    name: str
    url: str

    @classmethod
    def fromORM(cls, e: OAuth2ClientORM) -> ProviderData:
        """Create ProviderData from an ORM class."""
        return ProviderData(id=e.id, name=e.display_name, url=e.url)


@dataclass(frozen=True, eq=True, kw_only=True)
class RepositoryProviderData:
    """Repository provider match data."""

    provider: ProviderData
    connection: ProviderConnection | None
    repository_metadata: RepositoryMetadata | None


@dataclass(frozen=True, eq=True, kw_only=True)
class Metadata:
    """Metadata about a repository."""

    etag: str | None = None
    git_url: str
    web_url: str | None = None
    pull_permission: bool
    push_permission: bool | None = None

    @classmethod
    def fromRepoMeta(cls, rm: RepositoryMetadata) -> Metadata:
        """Create Metadata from RepositoryMetadata."""
        return Metadata(
            etag=rm.etag,
            git_url=rm.git_http_url,
            web_url=rm.web_url,
            pull_permission=rm.permissions.pull,
            push_permission=rm.permissions.push,
        )


class RepositoryMetadataError(StrEnum):
    """Possible errors when retrieving repository metadata."""

    metadata_unauthorized = "metadata_unauthorized"
    metadata_unknown = "metadata_unknown_error"


type RepositoryError = GitUrlError | RepositoryMetadataError


@dataclass(frozen=True, eq=True, kw_only=True)
class RepositoryDataResult:
    """Information when retrieving a repository."""

    provider: ProviderData | None = None
    connection: ProviderConnection | None = None
    error: RepositoryError | None = None
    metadata: Metadata | Literal["Unmodified"] | None = None

    def with_metadata(self, rm: RepositoryMetadata | Literal["304"] | RepositoryError) -> RepositoryDataResult:
        """Return a new result with metadatat set."""
        match rm:
            case "304":
                return dataclasses.replace(self, metadata="Unmodified")
            case GitUrlError() as err:
                return self.with_error(err)
            case RepositoryMetadataError() as err:
                return self.with_error(err)
            case RepositoryMetadata() as md:
                return dataclasses.replace(self, metadata=Metadata.fromRepoMeta(md))

    def with_provider(self, p: ProviderData | None) -> RepositoryDataResult:
        """Return a new result with the provider set."""
        return dataclasses.replace(self, provider=p)

    def with_provider_orm(self, p: OAuth2ClientORM | None) -> RepositoryDataResult:
        """Return a new result with the provider set."""
        return self.with_provider(ProviderData.fromORM(p) if p else None)

    def with_connection(self, c: ProviderConnection | None) -> RepositoryDataResult:
        """Return a new result with the connection set."""
        return dataclasses.replace(self, connection=c)

    def with_connection_orm(self, c: OAuth2ConnectionORM | None) -> RepositoryDataResult:
        """Return a new result with the connection set."""
        return self.with_connection(ProviderConnection.fromORM(c) if c else None)

    def with_error(self, err: RepositoryError | None) -> RepositoryDataResult:
        """Return a new result with the error set."""
        return dataclasses.replace(self, error=err)

    @property
    def is_error(self) -> bool:
        """Return whether this is an error result."""
        return self.error is not None

    @property
    def is_success(self) -> bool:
        """Return whether this is a success result."""
        return not self.error and self.metadata is not None
