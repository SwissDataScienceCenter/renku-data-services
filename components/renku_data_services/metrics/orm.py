"""SQLAlchemy schemas for the metrics database."""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, MetaData, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column
from ulid import ULID

from renku_data_services.utils.sqlalchemy import ULIDType

JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = MetaData(schema="metrics")


class MetricsORM(BaseORM):
    """Metrics staging table.

    Events are stored in this table and then processed by a background task that sends them to the actual metrics
    service.
    """

    __tablename__ = "metrics"

    id: Mapped[ULID] = mapped_column(
        "id", ULIDType, server_default=text("generate_ulid()"), primary_key=True, init=False
    )

    event: Mapped[str] = mapped_column("event", String(), nullable=False)
    """The type of the metrics (e.g., session_started, project_created, etc.)."""

    anonymous_user_id: Mapped[str] = mapped_column("anonymous_user_id", String(), nullable=False)

    timestamp: Mapped[datetime] = mapped_column(
        "timestamp", DateTime(timezone=True), init=False, server_default=func.now(), nullable=False
    )

    metadata_: Mapped[Optional[dict[str, Any]]] = mapped_column("metadata", JSONVariant, default=None, nullable=True)
    """The metrics metadata."""
