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
    updated_at: datetime

    @property
    def etag(self) -> str:
        """Entity tag value for this project object."""
        return compute_etag_from_timestamp(self.updated_at, include_quotes=True)
