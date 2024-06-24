"""Models for Sessions."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel

from renku_data_services.utils.etag import compute_etag_from_timestamp


class ConfigID(StrEnum):
    """The singleton ID allowed for the platform configuration."""

    config = "config"


@dataclass(frozen=True, eq=True, kw_only=True)
class PlatformConfig(BaseModel):
    """The configuration of RenkuLab."""

    id: ConfigID
    disable_ui: bool
    maintenance_banner: str
    status_page_id: str
    creation_date: datetime = field(default_factory=lambda: datetime.now(UTC).replace(microsecond=0))
    updated_at: datetime | None = field(default=None)

    @property
    def etag(self) -> str | None:
        """Entity tag value for this project object."""
        if self.updated_at is None:
            return None
        return compute_etag_from_timestamp(self.updated_at, include_quotes=True)
