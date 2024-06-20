"""SQLAlchemy's schemas for the group database."""

from datetime import datetime
from typing import Optional, cast

from sqlalchemy import CheckConstraint, DateTime, MetaData, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column, relationship
from sqlalchemy.schema import ForeignKey
from ulid import ULID

from renku_data_services.errors import errors
from renku_data_services.namespace import models
from renku_data_services.users.models import UserInfo, UserWithNamespace
from renku_data_services.users.orm import UserORM


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = MetaData(schema="common")


class GroupORM(BaseORM):
    """A Renku group."""

    __tablename__ = "groups"

    id: Mapped[str] = mapped_column("id", String(26), primary_key=True, default_factory=lambda: str(ULID()), init=False)
    name: Mapped[str] = mapped_column("name", String(99), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey(UserORM.keycloak_id), index=True, nullable=False)
    creation_date: Mapped[datetime] = mapped_column("creation_date", DateTime(timezone=True), server_default=func.now())
    namespace: Mapped["NamespaceORM"] = relationship(lazy="joined", init=False, repr=False, viewonly=True)
    description: Mapped[Optional[str]] = mapped_column("description", String(500), default=None)

    def dump(self) -> models.Group:
        """Create a group model from the GroupORM."""
        return models.Group(
            id=self.id,
            name=self.name,
            slug=self.namespace.slug,
            created_by=self.created_by,
            creation_date=self.creation_date,
            description=self.description,
        )


class NamespaceORM(BaseORM):
    """Renku current namespace slugs."""

    __tablename__ = "namespaces"
    __table_args__ = (
        CheckConstraint("(user_id IS NULL) <> (group_id IS NULL)", name="either_group_id_or_user_id_is_set"),
    )

    id: Mapped[str] = mapped_column("id", String(26), primary_key=True, default_factory=lambda: str(ULID()), init=False)
    slug: Mapped[str] = mapped_column(String(99), index=True, unique=True, nullable=False)
    group_id: Mapped[str | None] = mapped_column(
        ForeignKey(GroupORM.id, ondelete="CASCADE", name="namespaces_group_id_fk"),
        default=None,
        nullable=True,
        index=True,
    )
    group: Mapped[GroupORM | None] = relationship(lazy="joined", init=False, repr=False, viewonly=True)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey(UserORM.keycloak_id, ondelete="CASCADE", name="namespaces_user_keycloak_id_fk"),
        default=None,
        nullable=True,
        index=True,
    )
    user: Mapped[UserORM | None] = relationship(lazy="joined", init=False, repr=False, viewonly=True)

    def dump(self) -> models.Namespace:
        """Create a namespace model from the ORM."""
        if self.group_id is None and self.user_id is None:
            raise errors.ProgrammingError(
                message=f"Trying to convert a NamespaceORM with ID {self.id} to a model "
                "but the namespace is missing both the user and group ID"
            )
        if self.group is None and self.user is None:
            raise errors.ProgrammingError(
                message=f"Trying to convert a NamespaceORM with ID {self.id} to a model "
                "but the namespace is missing both the user and group relations"
            )
        created_by = self.user_id
        name: str | None = None
        if self.group:
            created_by = self.group.created_by
            name = self.group.name
        elif self.user:
            if self.user.first_name and self.user.last_name:
                name = f"{self.user.first_name} {self.user.last_name}"
            else:
                name = self.user.first_name or self.user.last_name
        # NOTE: Mypy should have inferred the 2 types below beacuse at the top we check that both values are not None
        created_by = cast(str, created_by)
        underlying_resource = cast(str, self.user_id or self.group_id)
        return models.Namespace(
            id=self.id,
            slug=self.slug,
            latest_slug=self.slug,
            created_by=created_by,
            kind=models.NamespaceKind.user if self.user_id else models.NamespaceKind.group,
            underlying_resource_id=underlying_resource,
            name=name,
        )

    def dump_user(self) -> UserWithNamespace:
        """Create a user with namespace from the ORM."""
        if self.user is None:
            raise errors.ProgrammingError(
                message="Cannot dump ORM namespace as namespace with user if the namespace "
                "has no associated user with it."
            )
        ns = self.dump()
        user_info = UserInfo(self.user.keycloak_id, self.user.first_name, self.user.last_name, self.user.email)
        return UserWithNamespace(user_info, ns)


class NamespaceOldORM(BaseORM):
    """Renku namespace slugs history."""

    __tablename__ = "namespaces_old"

    id: Mapped[str] = mapped_column("id", String(26), primary_key=True, default_factory=lambda: str(ULID()), init=False)
    slug: Mapped[str] = mapped_column(String(99), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, index=True, init=False, server_default=func.now())
    latest_slug_id: Mapped[str] = mapped_column(
        ForeignKey(NamespaceORM.id, ondelete="CASCADE"), nullable=False, index=True
    )
    latest_slug: Mapped[NamespaceORM] = relationship(lazy="joined", init=False, viewonly=True, repr=False)

    def dump(self) -> models.Namespace:
        """Create an namespace model from the ORM."""
        if self.latest_slug.group_id is None and self.latest_slug.user_id is None:
            raise errors.ProgrammingError(
                message=f"Trying to convert a NamespaceOldORM with ID {self.id} to a model "
                "but the latest namespace is missing both the user and group ID"
            )
        if self.latest_slug.group is None and self.latest_slug.user is None:
            raise errors.ProgrammingError(
                message=f"Trying to convert a NamespaceOldORM with ID {self.id} to a model "
                "but the latest namespace is missing both the user and group relations"
            )
        created_by = self.latest_slug.user_id
        if self.latest_slug.group:
            created_by = self.latest_slug.group.created_by
        # NOTE: Mypy should have inferred the 2 types below beacuse at the top we check that both values are not None
        created_by = cast(str, created_by)
        underlying_resource_id = cast(str, self.latest_slug.group_id or self.latest_slug.user_id)
        return models.Namespace(
            id=self.id,
            slug=self.slug,
            latest_slug=self.latest_slug.slug,
            created_by=created_by,
            kind=models.NamespaceKind.user if self.latest_slug.user_id else models.NamespaceKind.group,
            underlying_resource_id=underlying_resource_id,
        )
