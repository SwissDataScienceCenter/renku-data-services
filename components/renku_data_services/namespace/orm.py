"""SQLAlchemy's schemas for the group database."""

from datetime import datetime
from typing import Dict, Optional

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, MetaData, String
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
    namespace_id: Mapped[int] = mapped_column(ForeignKey(UserORM.id), index=True, nullable=False)
    created_by: Mapped[str] = mapped_column("created_by", String())
    creation_date: Mapped[datetime] = mapped_column("creation_date", DateTime(timezone=True))
    description: Mapped[Optional[str]] = mapped_column("description", String(500), default=None)
    members: Mapped[Dict[str, "GroupMemberORM"]] = relationship(
        # NOTE: the members of a group are keyed by the Keycloak ID
        back_populates="group",
        collection_class=attribute_keyed_dict("user_id"),
        default_factory=dict,
    )

    @classmethod
    def load(cls, group: models.Group):
        """Create GroupORM from the project model."""
        return cls(
            name=group.name,
            slug=group.slug,
            created_by=group.created_by,
            creation_date=group.creation_date,
            description=group.description,
        )

    def dump(self) -> models.Group:
        """Create a group model from the GroupORM."""
        return models.Group(
            id=self.id,
            name=self.name,
            slug=self.slug,
            created_by=self.created_by,
            creation_date=self.creation_date,
            description=self.description,
        )


class GroupMemberORM(BaseORM):
    """Renku group members."""

    __tablename__ = "group_members"

    id: Mapped[int] = mapped_column("id", Integer, primary_key=True, default=None, init=False)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    role: Mapped[int] = mapped_column("role", Integer)
    group_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True, default=None
    )
    group: Mapped[Optional[GroupORM]] = relationship(back_populates="members", default=None)

    @classmethod
    def load(cls, member: models.GroupMember):
        """Create GroupMemberORM from the model."""
        return cls(
            role=member.role.value,
            user_id=member.user_id,
            group_id=member.group_id,
        )

    def dump(self) -> models.GroupMember:
        """Create a group member model from the ORM."""
        return models.GroupMember(
            role=models.GroupRole(self.role),
            user_id=self.user_id,
            group_id=self.group_id,
        )


class NamespaceORM(BaseORM):
    __tablename__ = "namespaces"
    __table_args__ = (
        Index("namespaces_one_slug_is_latest", "slug", "latest_id", unique=True, postgresql_where="latest_id is NULL"),
        CheckConstraint("num_nulls(user_id, group_id) = 1", name="only_one_null_in_group_user_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    slug: Mapped[str] = mapped_column(index=True, unique=True, nullable=False)
    latest_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("namespaces.id", ondelete="CASCADE"), nullable=True, init=False, index=True
    )
    latest: Mapped[Optional["NamespaceORM"]] = relationship(remote_side=[id], lazy="joined", join_depth=1)
    user_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey(UserORM.id, ondelete="CASCADE"), index=True, default=None
    )
    group_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True, default=None
    )
