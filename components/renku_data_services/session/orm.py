"""SQLAlchemy's schemas for the sessions database."""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column
from ulid import ULID

from renku_data_services.session import models

metadata_obj = MetaData(schema="sessions")  # Has to match alembic ini section name


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = metadata_obj


class SessionORM(BaseORM):
    """A Renku native session."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column("id", String(26), primary_key=True, default_factory=lambda: str(ULID()), init=False)
    name: Mapped[str] = mapped_column("name", String(99))
    created_by_id: Mapped[str] = mapped_column("created_by_id", String())
    creation_date: Mapped[Optional[datetime]] = mapped_column("creation_date", DateTime(timezone=True))
    description: Mapped[Optional[str]] = mapped_column("description", String(500))
    environment_id: Mapped[str] = mapped_column("environment_id", String(500))  # TODO: This should be 26
    project_id: Mapped[str] = mapped_column("project_id", String(26))

    @classmethod
    def load(cls, session: models.Session):
        """Create SessionORM from the session model."""
        return cls(
            name=session.name,
            created_by_id=session.created_by.id,
            creation_date=session.creation_date,
            description=session.description,
            environment_id=session.environment_id,
            project_id=session.project_id,
        )

    def dump(self) -> models.Session:
        """Create a session model from the database session model."""
        return models.Session(
            id=self.id,
            name=self.name,
            created_by=models.Member(id=self.created_by_id),
            creation_date=self.creation_date,
            description=self.description,
            environment_id=self.environment_id,
            project_id=self.project_id,
        )
