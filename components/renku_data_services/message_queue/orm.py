"""SQLAlchemy schemas for the CRC database."""
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, MetaData, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column

JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = MetaData(schema="events")  # Has to match alembic ini section name


class EventORM(BaseORM):
    """Event table.

    This table is used to ensure message delivery.
    When changes are made to the database, the corresponding event is writte here in the same transaction.
    After changes are committed, the event is sent and the entry from this table deleted again.
    If any change was stored in the DB but e.g. the service crashed before sending the corresponding event, there
    would be a left-over entry here.
    On startup, any entry left here is resent and the entry deleted. This can result in duplicate events being sent
    and it's up to the receivers to deal with this, but this ensures that an event will be sent at least once.
    """

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True, default=None, init=False)
    """Unique id of the event."""

    timestamp_utc: Mapped[datetime] = mapped_column("timestamp_utc", DateTime(timezone=False), nullable=False)

    queue: Mapped[str] = mapped_column("queue", String())
    """The name of the queue to send the event to."""

    payload: Mapped[dict[str, Any]] = mapped_column("payload", JSONVariant)
    """The message payload."""
