"""SQLAlchemy schemas for the CRC database."""

import base64
import json
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, Identity, Index, Integer, MetaData, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column
from ulid import ULID

from renku_data_services.message_queue.models import Event, Reprovisioning
from renku_data_services.utils.sqlalchemy import ULIDType

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

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True, default=None, init=False)
    """Unique id of the event."""

    timestamp_utc: Mapped[datetime] = mapped_column("timestamp_utc", DateTime(timezone=False), nullable=False)

    queue: Mapped[str] = mapped_column("queue", String())
    """The name of the queue to send the event to."""

    payload: Mapped[dict[str, Any]] = mapped_column("payload", JSONVariant)
    """The message payload."""

    @classmethod
    def load(cls, event: Event) -> "EventORM":
        """Create an ORM object from an event."""
        message = event.serialize()
        if "payload" in message and isinstance(message["payload"], bytes):
            message["payload"] = base64.b64encode(message["payload"]).decode()
        now_utc = datetime.now(UTC).replace(tzinfo=None)
        return cls(timestamp_utc=now_utc, queue=event.queue, payload=message)

    def dump(self) -> Event:
        """Create an event from the ORM object."""
        message = deepcopy(self.payload)
        if "payload" in message and isinstance(message["payload"], str):
            message["payload"] = base64.b64decode(message["payload"])
        return Event(self.queue, message)

    def get_message_type(self) -> Optional[str]:
        """Return the message_type from the payload."""
        headers = self.payload.get("headers", "{}")
        headers_json = json.loads(headers)
        message_type = str(headers_json.get("type", ""))
        if message_type == "":
            return None
        else:
            return message_type


class ReprovisioningORM(BaseORM):
    """Reprovisioning table.

    This table is used to make sure that only one instance of reprovisioning is run at any given time.
    It gets updated with the reprovisioning progress.
    """

    __tablename__ = "reprovisioning"
    __table_args__ = (Index("ix_reprovisioning_single_row_constraint", text("(( true ))"), unique=True),)

    id: Mapped[ULID] = mapped_column("id", ULIDType, primary_key=True, default_factory=lambda: str(ULID()), init=False)
    start_date: Mapped[datetime] = mapped_column("start_date", DateTime(timezone=True), nullable=False)

    def dump(self) -> Reprovisioning:
        """Create a Reprovisioning from the ORM object."""
        return Reprovisioning(id=self.id, start_date=self.start_date)


class SearchUpdatesORM(BaseORM):
    """Table for updates to SOLR."""

    __tablename__ = "search_updates"

    id: Mapped[int] = mapped_column("id", ULIDType, primary_key=True, server_default=text("generate_ulid()"), init=False)
    """Artificial identifier with stable order."""

    entity_id: Mapped[str] = mapped_column("entity_id", String(), unique=True, index=True)
    """The id of the entity (user, project, etc)."""

    entity_type: Mapped[str] = mapped_column("entity_type", String(), nullable=False)
    """The entity type as a string."""

    created_at: Mapped[datetime] = mapped_column("created_at", DateTime(timezone=True), nullable=False)
    """A timestamp to indicate insertion time."""

    payload: Mapped[dict[str, Any]] = mapped_column("payload", JSONVariant, nullable=False)
    """The SOLR document of the entity as JSON."""
