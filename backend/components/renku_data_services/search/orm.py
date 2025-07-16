"""ORM definitions for search update staging table."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, MetaData, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column
from ulid import ULID

from renku_data_services.utils.sqlalchemy import ULIDType

JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = MetaData(schema="events")  # Has to match alembic ini section name


class RecordState(StrEnum):
    """Indicates the state of a row wrt processing."""

    Locked = "Locked"
    Failed = "Failed"


class SearchUpdatesORM(BaseORM):
    """Table for updates to SOLR."""

    __tablename__ = "search_updates"

    id: Mapped[ULID] = mapped_column(
        "id", ULIDType, primary_key=True, server_default=text("generate_ulid()"), init=False
    )
    """Artificial identifier with stable order."""

    entity_id: Mapped[str] = mapped_column("entity_id", String(100), unique=True, index=True)
    """The id of the entity (user, project, etc)."""

    entity_type: Mapped[str] = mapped_column("entity_type", String(100), nullable=False)
    """The entity type as a string."""

    created_at: Mapped[datetime] = mapped_column("created_at", DateTime(timezone=True), nullable=False)
    """A timestamp to indicate insertion time."""

    payload: Mapped[dict[str, Any]] = mapped_column("payload", JSONVariant, nullable=False)
    """The SOLR document of the entity as JSON."""

    state: Mapped[RecordState] = mapped_column("state", Enum(RecordState), nullable=True, init=False)
    """State for marking rows."""
