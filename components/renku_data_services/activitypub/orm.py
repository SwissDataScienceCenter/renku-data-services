"""SQLAlchemy's schemas for the ActivityPub database."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, MetaData, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column, relationship
from ulid import ULID

from renku_data_services.base_orm.registry import COMMON_ORM_REGISTRY
from renku_data_services.activitypub import models
from renku_data_services.project.orm import ProjectORM
from renku_data_services.users.orm import UserORM
from renku_data_services.utils.sqlalchemy import ULIDType


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = MetaData(schema="activitypub")
    registry = COMMON_ORM_REGISTRY


class ActivityPubActorORM(BaseORM):
    """ActivityPub actor."""

    __tablename__ = "actors"
    __table_args__ = (
        Index("ix_actors_username", "username", unique=True),
        Index("ix_actors_user_id", "user_id"),
        Index("ix_actors_project_id", "project_id"),
    )

    id: Mapped[ULID] = mapped_column(
        "id", ULIDType, primary_key=True, default_factory=lambda: str(ULID()), init=False
    )
    username: Mapped[str] = mapped_column("username", String(255), nullable=False)
    name: Mapped[Optional[str]] = mapped_column("name", String(255), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column("summary", Text, nullable=True)
    type: Mapped[models.ActorType] = mapped_column("type", String(50), nullable=False)
    user_id: Mapped[Optional[str]] = mapped_column(
        "user_id", ForeignKey(UserORM.keycloak_id, ondelete="CASCADE"), nullable=True
    )
    project_id: Mapped[Optional[ULID]] = mapped_column(
        "project_id", ForeignKey(ProjectORM.id, ondelete="CASCADE"), nullable=True
    )
    private_key_pem: Mapped[Optional[str]] = mapped_column("private_key_pem", Text, nullable=True, default=None)
    public_key_pem: Mapped[Optional[str]] = mapped_column("public_key_pem", Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        "created_at", DateTime(timezone=True), default=func.now(), nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        "updated_at", DateTime(timezone=True), default=None, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    followers: Mapped[list["ActivityPubFollowerORM"]] = relationship(
        primaryjoin="ActivityPubActorORM.id == ActivityPubFollowerORM.actor_id",
        back_populates="actor",
        cascade="all, delete-orphan",
        lazy="selectin",
        default_factory=list,
    )

    def dump(self) -> models.ActivityPubActor:
        """Create an ActivityPubActor model from the ORM."""
        return models.ActivityPubActor(
            id=self.id,
            username=self.username,
            name=self.name,
            summary=self.summary,
            type=self.type,
            user_id=self.user_id,
            project_id=self.project_id,
            created_at=self.created_at,
            updated_at=self.updated_at,
            private_key_pem=self.private_key_pem,
            public_key_pem=self.public_key_pem,
        )


class ActivityPubFollowerORM(BaseORM):
    """ActivityPub follower."""

    __tablename__ = "followers"
    __table_args__ = (
        Index("ix_followers_actor_id", "actor_id"),
        Index("ix_followers_actor_id_follower_actor_uri", "actor_id", "follower_actor_uri", unique=True),
    )

    id: Mapped[ULID] = mapped_column(
        "id", ULIDType, primary_key=True, default_factory=lambda: str(ULID()), init=False
    )
    actor_id: Mapped[ULID] = mapped_column(
        "actor_id", ULIDType, ForeignKey(ActivityPubActorORM.id, ondelete="CASCADE"), nullable=False
    )
    follower_actor_uri: Mapped[str] = mapped_column("follower_actor_uri", String(2048), nullable=False)
    accepted: Mapped[bool] = mapped_column("accepted", Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        "created_at", DateTime(timezone=True), default=func.now(), nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        "updated_at", DateTime(timezone=True), default=None, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    actor: Mapped[ActivityPubActorORM] = relationship(
        primaryjoin="ActivityPubActorORM.id == ActivityPubFollowerORM.actor_id",
        back_populates="followers",
        lazy="selectin",
        default=None,
    )

    def dump(self) -> models.ActivityPubFollower:
        """Create an ActivityPubFollower model from the ORM."""
        return models.ActivityPubFollower(
            id=self.id,
            actor_id=self.actor_id,
            follower_actor_uri=self.follower_actor_uri,
            accepted=self.accepted,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )
