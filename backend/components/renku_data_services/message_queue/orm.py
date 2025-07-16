"""SQLAlchemy schemas for the message queue database."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, MetaData, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column
from ulid import ULID

from renku_data_services.message_queue.models import Reprovisioning
from renku_data_services.utils.sqlalchemy import ULIDType

JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = MetaData(schema="events")  # Has to match alembic ini section name


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
