"""SQLAlchemy's schemas for the group database."""

from datetime import datetime
from typing import Optional

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
        if self.group_id and self.group:
            return models.Namespace(
                id=self.id,
                slug=self.slug,
                kind=models.NamespaceKind.group,
                created_by=self.group.created_by,
                underlying_resource_id=self.group_id,
                latest_slug=self.slug,
                name=self.group.name,
            )

        if not self.user or not self.user_id:
            raise errors.ProgrammingError(message="Found a namespace that has no group or user associated with it.")

        name = (
            f"{self.user.first_name} {self.user.last_name}"
            if self.user.first_name and self.user.last_name
            else self.user.first_name or self.user.last_name
        )
        return models.Namespace(
            id=self.id,
            slug=self.slug,
            kind=models.NamespaceKind.user,
            created_by=self.user_id,
            underlying_resource_id=self.user_id,
            latest_slug=self.slug,
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
        if self.latest_slug.group_id and self.latest_slug.group:
            return models.Namespace(
                id=self.id,
                slug=self.slug,
                latest_slug=self.slug,
                created_by=self.latest_slug.group.created_by,
                kind=models.NamespaceKind.group,
                underlying_resource_id=self.latest_slug.group_id,
                name=self.latest_slug.group.name,
            )

        if not self.latest_slug.user or not self.latest_slug.user_id:
            raise errors.ProgrammingError(
                message="Found an old namespace that has no group or user associated with it in its latest slug."
            )

        name = (
            f"{self.latest_slug.user.first_name} {self.latest_slug.user.last_name}"
            if self.latest_slug.user.first_name and self.latest_slug.user.last_name
            else self.latest_slug.user.first_name or self.latest_slug.user.last_name
        )
        return models.Namespace(
            id=self.id,
            slug=self.slug,
            latest_slug=self.latest_slug.slug,
            created_by=self.latest_slug.user_id,
            kind=models.NamespaceKind.user,
            underlying_resource_id=self.latest_slug.user_id,
            name=name,
        )
