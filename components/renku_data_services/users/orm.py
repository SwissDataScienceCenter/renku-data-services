"""SQLAlchemy schemas for the CRC database."""

from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import JSON, DateTime, Integer, LargeBinary, MetaData, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column, relationship

from renku_data_services.base_orm.registry import COMMON_ORM_REGISTRY
from renku_data_services.users.models import PinnedProjects, UserInfo, UserPreferences

if TYPE_CHECKING:
    from renku_data_services.namespace.orm import NamespaceORM

JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = MetaData(schema="users")  # Has to match alembic ini section name
    registry = COMMON_ORM_REGISTRY


class UserORM(BaseORM):
    """User data table."""

    __tablename__ = "users"
    keycloak_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    namespace: Mapped["NamespaceORM"] = relationship(repr=False, back_populates="user", lazy="selectin")
    first_name: Mapped[Optional[str]] = mapped_column(String(256), default=None)
    last_name: Mapped[Optional[str]] = mapped_column(String(256), default=None)
    email: Mapped[Optional[str]] = mapped_column(String(320), default=None, index=True)
    secret_key: Mapped[Optional[bytes]] = mapped_column(LargeBinary(), default=None, repr=False)
    id: Mapped[int] = mapped_column(primary_key=True, init=False)

    def dump(self) -> UserInfo:
        """Create a user object from the ORM object."""
        return UserInfo(
            id=self.keycloak_id,
            first_name=self.first_name,
            last_name=self.last_name,
            email=self.email,
            namespace=self.namespace.dump() if self.namespace else None,
        )

    @classmethod
    def load(cls, user: UserInfo) -> "UserORM":
        """Create an ORM object from the user object."""
        return cls(
            keycloak_id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
            namespace=NamespaceORM.load(user.namespace),
        )


class LastKeycloakEventTimestamp(BaseORM):
    """The latest event timestamp processed from Keycloak."""

    __tablename__ = "last_keycloak_event_timestamp"
    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    timestamp_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), default_factory=datetime.utcnow)


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
    def load(cls, user_preferences: UserPreferences) -> "UserPreferencesORM":
        """Create UserPreferencesORM from the user preferences model."""
        return cls(
            user_id=user_preferences.user_id,
            pinned_projects=user_preferences.pinned_projects.model_dump(),
        )

    def dump(self) -> UserPreferences:
        """Create a user preferences model from the ORM object."""
        return UserPreferences(user_id=self.user_id, pinned_projects=PinnedProjects.from_dict(self.pinned_projects))
