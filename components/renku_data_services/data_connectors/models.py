"""Models for data connectors."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from ulid import ULID

from renku_data_services.authz.models import Visibility
from renku_data_services.base_models.core import (
    DataConnectorInProjectPath,
    DataConnectorPath,
    DataConnectorSlug,
    NamespacePath,
    ProjectPath,
)
from renku_data_services.data_connectors.doi.models import DOI
from renku_data_services.namespace.models import GroupNamespace, ProjectNamespace, UserNamespace
from renku_data_services.storage.rclone import RCloneDOIMetadata
from renku_data_services.utils.etag import compute_etag_from_fields

if TYPE_CHECKING:
    from renku_data_services.data_connectors.apispec import RCloneOption


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
    creation_date: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = field(default=None)
    description: str | None = None
    keywords: list[str] | None = None
    storage: CloudStorageCore


@dataclass(frozen=True, eq=True, kw_only=True)
class DataConnector(BaseDataConnector):
    """Data connector model."""

    id: ULID
    namespace: UserNamespace | GroupNamespace | ProjectNamespace
    updated_at: datetime

    @property
    def etag(self) -> str:
        """Entity tag value for this data connector object."""
        return compute_etag_from_fields(self.updated_at, self.path.serialize())

    @property
    def path(self) -> DataConnectorPath | DataConnectorInProjectPath:
        """The full path (i.e. sequence of slugs) for the data connector including group or user and/or project."""
        return self.namespace.path / DataConnectorSlug(self.slug)


@dataclass(frozen=True, eq=True, kw_only=True)
class UnsavedDataConnector(BaseDataConnector):
    """A data connector that hasn't been stored in the database."""

    namespace: NamespacePath | ProjectPath

    @property
    def path(self) -> DataConnectorPath | DataConnectorInProjectPath:
        """The full path (i.e. sequence of slugs) for the data connector including group or user and/or project."""
        return self.namespace / DataConnectorSlug(self.slug)


@dataclass(frozen=True, eq=True, kw_only=True)
class GlobalDataConnector(BaseDataConnector):
    """Global data connector model."""

    id: ULID
    namespace: Final[None] = field(default=None, init=False)
    updated_at: datetime
    publisher_name: str | None = None
    publisher_url: str | None = None
    doi: DOI | None = None

    @property
    def etag(self) -> str:
        """Entity tag value for this data connector object."""
        return compute_etag_from_fields(self.updated_at)


@dataclass(frozen=True, eq=True, kw_only=True)
class UnsavedGlobalDataConnector(BaseDataConnector):
    """Global data connector model."""

    namespace: None = None
    publisher_name: str | None = None
    publisher_url: str | None = None
    doi: DOI | None = None


@dataclass(frozen=True, eq=True, kw_only=True)
class PrevalidatedGlobalDataConnector:
    """Global data connector model that is unsaved but has been pre-validated."""

    data_connector: UnsavedGlobalDataConnector
    rclone_metadata: RCloneDOIMetadata | None = None


@dataclass(frozen=True, eq=True, kw_only=True)
class DeletedDataConnector:
    """A dataconnector that has been deleted."""

    id: ULID


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
    namespace: NamespacePath | ProjectPath | None
    slug: str | None
    visibility: Visibility | None
    description: str | None
    keywords: list[str] | None
    storage: CloudStorageCorePatch | None


@dataclass(frozen=True, eq=True, kw_only=True)
class CloudStorageCoreWithSensitiveFields(CloudStorageCore):
    """Remote storage configuration model with sensitive fields."""

    sensitive_fields: list["RCloneOption"]


@dataclass(frozen=True, eq=True, kw_only=True)
class DataConnectorUpdate:
    """Information about the update of a data connector."""

    old: DataConnector | GlobalDataConnector
    new: DataConnector | GlobalDataConnector


@dataclass(frozen=True, eq=True, kw_only=True)
class UnsavedDataConnectorToProjectLink:
    """Base model for a link from a data connector to a project."""

    data_connector_id: ULID
    project_id: ULID


@dataclass(frozen=True, eq=True, kw_only=True)
class DataConnectorToProjectLink(UnsavedDataConnectorToProjectLink):
    """A link from a data connector to a project."""

    id: ULID
    project_path: str
    created_by: str
    creation_date: datetime
    updated_at: datetime


@dataclass(frozen=True, eq=True, kw_only=True)
class DataConnectorSecret:
    """Data connector secret model."""

    name: str
    user_id: str
    data_connector_id: ULID
    secret_id: ULID


@dataclass(frozen=True, eq=True, kw_only=True)
class DataConnectorSecretUpdate:
    """Secret to be saved for a data connector."""

    name: str
    value: str | None


@dataclass
class DataConnectorPermissions:
    """The permissions of a user on a given data connector."""

    write: bool
    delete: bool
    change_membership: bool


@dataclass
class DataConnectorWithSecrets:
    """A data connector with its secrets."""

    data_connector: DataConnector | GlobalDataConnector
    secrets: list[DataConnectorSecret] = field(default_factory=list)
