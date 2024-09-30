"""Models for data connectors."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ulid import ULID

from renku_data_services.authz.models import Visibility
from renku_data_services.namespace.models import Namespace
from renku_data_services.utils.etag import compute_etag_from_timestamp

if TYPE_CHECKING:
    from renku_data_services.storage.rclone import RCloneOption


@dataclass(frozen=True, eq=True, kw_only=True)
class CloudStorageCore:
    """Remote storage configuration model."""

    storage_type: str
    configuration: dict[str, Any]
    source_path: str
    target_path: str
    readonly: bool


@dataclass(frozen=True, eq=True, kw_only=True)
class BaseDataConnector:
    """Base data connector model."""

    name: str
    slug: str
    visibility: Visibility
    created_by: str
    creation_date: datetime = field(default_factory=lambda: datetime.now(UTC).replace(microsecond=0))
    updated_at: datetime | None = field(default=None)
    description: str | None = None
    keywords: list[str] | None = None
    storage: CloudStorageCore


@dataclass(frozen=True, eq=True, kw_only=True)
class DataConnector(BaseDataConnector):
    """Data connector model."""

    id: ULID
    namespace: Namespace
    updated_at: datetime

    @property
    def etag(self) -> str:
        """Entity tag value for this data connector object."""
        return compute_etag_from_timestamp(self.updated_at, include_quotes=True)


@dataclass(frozen=True, eq=True, kw_only=True)
class UnsavedDataConnector(BaseDataConnector):
    """A data connector that hasn't been stored in the database."""

    namespace: str


@dataclass(frozen=True, eq=True, kw_only=True)
class CloudStorageCorePatch:
    """Model for changes requested on a remote storage configuration."""

    storage_type: str | None
    configuration: dict[str, Any] | None
    source_path: str | None
    target_path: str | None
    readonly: bool | None


@dataclass(frozen=True, eq=True, kw_only=True)
class DataConnectorPatch:
    """Model for changes requested on a data connector."""

    name: str | None
    namespace: str | None
    slug: str | None
    visibility: Visibility | None
    description: str | None
    keywords: list[str] | None
    storage: CloudStorageCorePatch | None


@dataclass(frozen=True, eq=True, kw_only=True)
class CloudStorageCoreWithSensitiveFields(CloudStorageCore):
    """Remote storage configuration model with sensitive fields."""

    sensitive_fields: list["RCloneOption"]
