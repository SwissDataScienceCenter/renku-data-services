"""SQLAlchemy's schemas for the group database."""

from datetime import datetime
from typing import Dict, Optional

from sqlalchemy import CheckConstraint, DateTime, Integer, MetaData, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, attribute_keyed_dict, mapped_column, relationship
from sqlalchemy.schema import ForeignKey
from ulid import ULID

from renku_data_services.namespace import models
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
    creation_date: Mapped[datetime] = mapped_column("creation_date", DateTime(timezone=True))
    latest_ns_slug: Mapped["NamespaceORM"] = relationship(lazy="joined")
    description: Mapped[Optional[str]] = mapped_column("description", String(500), default=None)
    members: Mapped[Dict[str, "GroupMemberORM"]] = relationship(
        # NOTE: the members of a group are keyed by the Keycloak ID
        back_populates="group",
        collection_class=attribute_keyed_dict("user_id"),
        default_factory=dict,
    )

    def dump(self) -> models.Group:
        """Create a group model from the GroupORM."""
        return models.Group(
            id=self.id,
            name=self.name,
            slug=self.latest_ns_slug.slug,
            created_by=self.created_by,
            creation_date=self.creation_date,
            description=self.description,
        )


class GroupMemberORM(BaseORM):
    """Renku group members."""

    __tablename__ = "group_members"

    id: Mapped[int] = mapped_column("id", Integer, primary_key=True, default=None, init=False)
    user_id: Mapped[str] = mapped_column(ForeignKey(UserORM.keycloak_id, ondelete="CASCADE"), nullable=False)
    role: Mapped[int] = mapped_column("role", Integer)
    group_id: Mapped[str] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True, nullable=False, init=False
    )
    group: Mapped[GroupORM] = relationship(back_populates="members", init=False)

    @classmethod
    def load(cls, member: models.GroupMember):
        """Create GroupMemberORM from the model."""
        return cls(
            role=member.role.value,
            user_id=member.user_id,
        )

    def dump(self) -> models.GroupMember:
        """Create a group member model from the ORM."""
        return models.GroupMember(
            role=models.GroupRole(self.role),
            user_id=self.user_id,
            group_id=self.group_id,
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
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey(UserORM.keycloak_id, ondelete="CASCADE", name="namespaces_user_keycloak_id_fk"),
        default=None,
        nullable=True,
        index=True,
    )

    def dump(self) -> models.Namespace:
        """Create a namespace model from the ORM."""
        return models.Namespace(
            id=self.id,
            slug=self.slug,
            latest_slug=self.latest_ns_slug.slug if self.latest_ns_slug else None,
            created_by=self.user_id,
            kind=models.NamespaceKind.user if self.user_id else models.NamespaceKind.group,
        )


class NamespaceOldORM(BaseORM):
    """Renku namespace slugs history."""

    __tablename__ = "namespaces_old"

    id: Mapped[str] = mapped_column("id", String(26), primary_key=True, default_factory=lambda: str(ULID()), init=False)
    slug: Mapped[str] = mapped_column(String(99), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, index=True, init=False, server_default=func.now())
    latest_slug_id: Mapped[int] = mapped_column(
        ForeignKey(NamespaceORM.id, ondelete="CASCADE"), nullable=False, index=True
    )
    latest_slug: Mapped[NamespaceORM] = relationship(lazy="joined", init=False)

    def dump(self) -> models.Namespace:
        """Create an namespace model from the ORM."""
        return models.Namespace(
            id=self.id,
            slug=self.slug,
            latest_slug=self.latest_ns_slug.slug if self.latest_ns_slug else None,
            created_by=self.latest_slug.user_id,
            kind=models.NamespaceKind.user if self.latest_slug.user_id else models.NamespaceKind.group,
        )
