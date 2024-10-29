"""SQLAlchemy's schemas for the group database."""

from datetime import datetime
from typing import Optional, Self, cast

from sqlalchemy import CheckConstraint, DateTime, Identity, Index, Integer, MetaData, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column, relationship
from sqlalchemy.schema import ForeignKey
from sqlalchemy.util import hybridproperty
from ulid import ULID

from renku_data_services.base_orm.registry import COMMON_ORM_REGISTRY
from renku_data_services.data_connectors.orm import DataConnectorORM
from renku_data_services.errors import errors
from renku_data_services.namespace import models
from renku_data_services.project.orm import ProjectORM
from renku_data_services.users.models import UserInfo
from renku_data_services.users.orm import UserORM
from renku_data_services.utils.sqlalchemy import ULIDType


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = MetaData(schema="common")
    registry = COMMON_ORM_REGISTRY


class GroupORM(BaseORM):
    """A Renku group."""

    __tablename__ = "groups"

    id: Mapped[ULID] = mapped_column("id", ULIDType, primary_key=True, default_factory=lambda: str(ULID()), init=False)
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

    id: Mapped[ULID] = mapped_column("id", ULIDType, primary_key=True, default_factory=lambda: str(ULID()), init=False)
    slug: Mapped[str] = mapped_column(String(99), index=True, unique=True, nullable=False)
    group_id: Mapped[ULID | None] = mapped_column(
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

    @hybridproperty
    def created_by(self) -> str:
        """User that created this namespace."""
        if self.group is not None:
            return self.group.created_by
        elif self.user_id is not None:
            return self.user_id

        raise errors.ProgrammingError(
            message=f"Found a namespace {self.slug} that has no group or user associated with it."
        )

    @hybridproperty
    def creation_date(self) -> datetime | None:
        """When this namespace was created."""
        if self.group is not None:
            return self.group.creation_date
        return None

    def dump(self) -> models.Namespace:
        """Create a namespace model from the ORM."""
        if self.group_id and self.group:
            return models.Namespace(
                id=self.id,
                slug=self.slug,
                kind=models.NamespaceKind.group,
                created_by=self.created_by,
                creation_date=self.creation_date,
                underlying_resource_id=self.group_id,
                latest_slug=self.slug,
                name=self.group.name,
            )

        if not self.user or not self.user_id:
            raise errors.ProgrammingError(
                message=f"Found a namespace {self.slug} that has no group or user associated with it."
            )

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
            creation_date=self.creation_date,
            underlying_resource_id=self.user_id,
            latest_slug=self.slug,
            name=name,
        )

    def dump_user(self) -> UserInfo:
        """Create a user with namespace from the ORM."""
        if self.user is None:
            raise errors.ProgrammingError(
                message="Cannot dump ORM namespace as namespace with user if the namespace "
                "has no associated user with it."
            )
        ns = self.dump()
        user_info = UserInfo(
            id=self.user.keycloak_id,
            first_name=self.user.first_name,
            last_name=self.user.last_name,
            email=self.user.email,
            namespace=ns,
        )
        return user_info

    @classmethod
    def load(cls, ns: models.Namespace) -> Self:
        """Create an ORM object from the user object."""
        match ns.kind:
            case models.NamespaceKind.group:
                return cls(slug=ns.slug, group_id=cast(ULID, ns.underlying_resource_id))
            case models.NamespaceKind.user:
                return cls(slug=ns.slug, user_id=cast(str, ns.underlying_resource_id))

        raise errors.ValidationError(message=f"Unknown namespace kind {ns.kind}")


class NamespaceOldORM(BaseORM):
    """Renku namespace slugs history."""

    __tablename__ = "namespaces_old"

    id: Mapped[ULID] = mapped_column("id", ULIDType, primary_key=True, default_factory=lambda: str(ULID()), init=False)
    slug: Mapped[str] = mapped_column(String(99), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, index=True, init=False, server_default=func.now())
    latest_slug_id: Mapped[ULID] = mapped_column(
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
                created_by=self.latest_slug.created_by,
                creation_date=self.created_at,
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
            creation_date=self.created_at,
            kind=models.NamespaceKind.user,
            underlying_resource_id=self.latest_slug.user_id,
            name=name,
        )


class EntitySlugORM(BaseORM):
    """Entity slugs."""

    __tablename__ = "entity_slugs"
    __table_args__ = (
        Index("entity_slugs_unique_slugs", "namespace_id", "slug", unique=True),
        CheckConstraint(
            "CAST (project_id IS NOT NULL AS int) + CAST (data_connector_id IS NOT NULL AS int) BETWEEN 0 AND 1",
            name="either_project_id_or_data_connector_id_is_set",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True, init=False)
    slug: Mapped[str] = mapped_column(String(99), index=True, nullable=False)
    project_id: Mapped[ULID | None] = mapped_column(
        ForeignKey(ProjectORM.id, ondelete="CASCADE", name="entity_slugs_project_id_fk"), index=True, nullable=True
    )
    project: Mapped[ProjectORM | None] = relationship(init=False, repr=False, back_populates="slug")
    data_connector_id: Mapped[ULID | None] = mapped_column(
        ForeignKey(DataConnectorORM.id, ondelete="CASCADE", name="entity_slugs_data_connector_id_fk"),
        index=True,
        nullable=True,
    )
    data_connector: Mapped[DataConnectorORM | None] = relationship(init=False, repr=False, back_populates="slug")
    namespace_id: Mapped[ULID] = mapped_column(
        ForeignKey(NamespaceORM.id, ondelete="CASCADE", name="entity_slugs_namespace_id_fk"), index=True
    )
    namespace: Mapped[NamespaceORM] = relationship(lazy="joined", init=False, repr=False, viewonly=True)

    @classmethod
    def create_project_slug(cls, slug: str, project_id: ULID, namespace_id: ULID) -> "EntitySlugORM":
        """Create an entity slug for a project."""
        return cls(
            slug=slug,
            project_id=project_id,
            data_connector_id=None,
            namespace_id=namespace_id,
        )

    @classmethod
    def create_data_connector_slug(cls, slug: str, data_connector_id: ULID, namespace_id: ULID) -> "EntitySlugORM":
        """Create an entity slug for a data connector."""
        return cls(
            slug=slug,
            project_id=None,
            data_connector_id=data_connector_id,
            namespace_id=namespace_id,
        )


class EntitySlugOldORM(BaseORM):
    """Entity slugs history."""

    __tablename__ = "entity_slugs_old"

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True, init=False)
    slug: Mapped[str] = mapped_column(String(99), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, init=False, server_default=func.now()
    )
    latest_slug_id: Mapped[int] = mapped_column(
        ForeignKey(EntitySlugORM.id, ondelete="CASCADE"),
        nullable=False,
        init=False,
        index=True,
    )
    latest_slug: Mapped[EntitySlugORM] = relationship(lazy="joined", repr=False, viewonly=True)
