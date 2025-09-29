"""Models for the platform configuration."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from renku_data_services.utils.etag import compute_etag_from_timestamp


class ConfigID(StrEnum):
    """The singleton ID allowed for the platform configuration."""

    config = "config"


@dataclass(frozen=True, eq=True, kw_only=True)
class PlatformConfig:
    """The configuration of RenkuLab."""

    id: ConfigID
    incident_banner: str
    creation_date: datetime = field(default_factory=lambda: datetime.now(UTC).replace(microsecond=0))
    updated_at: datetime

    @property
    def etag(self) -> str:
        """Entity tag value for this project object."""
        return compute_etag_from_timestamp(self.updated_at)


@dataclass(frozen=True, eq=True, kw_only=True)
class PlatformConfigPatch:
    """Model for changes requested on the platform configuration."""

    incident_banner: str | None = None
