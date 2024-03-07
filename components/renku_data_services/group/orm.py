"""SQLAlchemy's schemas for the group database."""

from datetime import datetime
from typing import Dict, Optional

from sqlalchemy import DateTime, Integer, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, attribute_keyed_dict, mapped_column, relationship
from sqlalchemy.schema import ForeignKey
from ulid import ULID

from renku_data_services.group import models

metadata_obj = MetaData(schema="groups")  # Has to match alembic ini section name


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = metadata_obj


class GroupORM(BaseORM):
    """A Renku group."""

    __tablename__ = "groups"

    id: Mapped[str] = mapped_column("id", String(26), primary_key=True, default_factory=lambda: str(ULID()), init=False)
    name: Mapped[str] = mapped_column("name", String(99), index=True)
    slug: Mapped[str] = mapped_column("slug", String(99), index=True, unique=True)
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
