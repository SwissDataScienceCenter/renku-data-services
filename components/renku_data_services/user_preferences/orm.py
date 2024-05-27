"""SQLAlchemy schemas for the user preferences database."""

from typing import Any

from sqlalchemy import JSON, Integer, MetaData, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column

from renku_data_services.user_preferences import models

JSONVariant = JSON().with_variant(JSONB(), "postgresql")

metadata_obj = MetaData(schema="user_preferences")  # Has to match alembic ini section name


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = metadata_obj


class UserPreferencesORM(BaseORM):
    """Stored user preferences."""

    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column("id", Integer, primary_key=True, default=None, init=False)
    """Id of this user preferences object."""

    user_id: Mapped[str] = mapped_column("user_id", String(), unique=True)
    """Id of the user."""

    pinned_projects: Mapped[dict[str, Any]] = mapped_column("pinned_projects", JSONVariant)
    """Pinned projects."""

    @classmethod
    def load(cls, user_preferences: models.UserPreferences) -> "UserPreferencesORM":
        """Create UserPreferencesORM from the user preferences model."""
        return cls(
            user_id=user_preferences.user_id,
            pinned_projects=user_preferences.pinned_projects.model_dump(),
        )

    def dump(self):
        """Create a user preferences model from the ORM object."""
        return models.UserPreferences(
            user_id=self.user_id, pinned_projects=models.PinnedProjects.from_dict(self.pinned_projects)
        )
