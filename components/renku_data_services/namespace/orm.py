"""SQLAlchemy's schemas for the group database."""

from datetime import datetime
from typing import Optional, Self

from sqlalchemy import CheckConstraint, DateTime, Identity, Index, Integer, MetaData, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column, relationship
from sqlalchemy.schema import ForeignKey
from ulid import ULID

from renku_data_services.base_models.core import NamespacePath
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
    user: Mapped[UserORM | None] = relationship(
        lazy="joined", back_populates="namespace", init=False, repr=False, viewonly=True
    )
    old_namespaces: Mapped[list["NamespaceOldORM"]] = relationship(
        back_populates="latest_slug",
        default_factory=list,
        repr=False,
        init=False,
        viewonly=True,
    )

    @property
    def created_by(self) -> str:
        """User that created this namespace."""
        if self.group is not None:
            return self.group.created_by
        elif self.user_id:
            return self.user_id
        raise errors.ProgrammingError(
            message=f"Found a namespace {self.slug} that has no group or user associated with it."
        )

    @property
    def creation_date(self) -> datetime | None:
        """When this namespace was created."""
        return self.group.creation_date if self.group else None

    @property
    def name(self) -> str | None:
        """Return the name of the underlying resource."""
        if self.group is not None:
            return self.group.name
        elif self.user is not None:
            return (
                f"{self.user.first_name} {self.user.last_name}"
                if self.user.first_name and self.user.last_name
                else self.user.first_name or self.user.last_name
            )
        raise errors.ProgrammingError(
            message=f"Found a namespace {self.slug} that has no group or user associated with it."
        )

    def dump_group_namespace(self) -> models.GroupNamespace:
        """Create a namespace model from the ORM."""
        if not self.group_id:
            raise errors.ProgrammingError(
                message="Expected a valid group_id when dumping NamespaceORM as group namespace."
            )
        return models.GroupNamespace(
            id=self.id,
            created_by=self.created_by,
            creation_date=self.creation_date,
            underlying_resource_id=self.group_id,
            latest_slug=self.slug,
            name=self.name,
            path=NamespacePath.from_strings(self.slug),
        )

    def dump_user_namespace(self) -> models.UserNamespace:
        """Create a namespace model from the ORM."""
        if self.user_id is None:
            raise errors.ProgrammingError(
                message="Expected a user_id in the NamespaceORM when dumping the object, but got None."
            )
        return models.UserNamespace(
            id=self.id,
            created_by=self.created_by,
            creation_date=self.creation_date,
            underlying_resource_id=self.user_id,
            latest_slug=self.slug,
            name=self.name,
            path=NamespacePath.from_strings(self.slug),
        )

    def dump(self) -> models.UserNamespace | models.GroupNamespace:
        """Create a namespace model from the ORM."""
        if self.group_id:
            return self.dump_group_namespace()
        else:
            return self.dump_user_namespace()

    def dump_user(self) -> UserInfo:
        """Create a user with namespace from the ORM."""
        if self.user is None:
            raise errors.ProgrammingError(
                message="Cannot dump ORM namespace as namespace with user if the namespace "
                "has no associated user with it."
            )
        # NOTE: calling `self.user.dump()` can cause sqlalchemy greenlet errors, as it tries to fetch the namespace
        # again from the db, even though the back_populates should take care of this and not require loading.
        ns = self.dump_user_namespace()
        user_info = UserInfo(
            id=self.user.keycloak_id,
            first_name=self.user.first_name,
            last_name=self.user.last_name,
            email=self.user.email,
            namespace=ns,
        )
        return user_info

    @classmethod
    def load_user(cls, ns: models.UserNamespace) -> Self:
        """Create an ORM object from the user namespace object."""
        return cls(slug=ns.path.first.value, user_id=ns.underlying_resource_id)

    @classmethod
    def load_group(cls, ns: models.GroupNamespace) -> Self:
        """Create an ORM object from the group namespace object."""
        return cls(slug=ns.path.first.value, group_id=ns.underlying_resource_id)


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

    def dump(self) -> models.UserNamespace | models.GroupNamespace:
        """Create an namespace model from the ORM."""
        if self.latest_slug.group_id and self.latest_slug.group:
            return models.GroupNamespace(
                id=self.id,
                latest_slug=self.slug,
                created_by=self.latest_slug.created_by,
                creation_date=self.created_at,
                underlying_resource_id=self.latest_slug.group_id,
                name=self.latest_slug.group.name,
                path=NamespacePath.from_strings(self.slug),
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
        return models.UserNamespace(
            id=self.id,
            latest_slug=self.latest_slug.slug,
            created_by=self.latest_slug.user_id,
            creation_date=self.created_at,
            underlying_resource_id=self.latest_slug.user_id,
            name=name,
            path=NamespacePath.from_strings(self.slug),
        )

    def dump_as_namespace_path(self) -> models.NamespacePath:
        """Create a namespace path."""
        return self.dump().path


class EntitySlugORM(BaseORM):
    """Entity slugs.

    Note that valid combinations here are:
    - namespace_id + project_id
    - namespace_id + project_id + data_connector_id
    - namespace_id + data_connector_id
    """

    __tablename__ = "entity_slugs"
    __table_args__ = (
        Index(
            "entity_slugs_unique_slugs",
            "namespace_id",
            "project_id",
            "data_connector_id",
            "slug",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        # NOTE: prevents 2 different projects from having the same slug
        # I.e. an invalid example like this:
        # namespace_id | project_id | data_connector_id | slug
        # 1            | 1          | NULL              | prj1
        # 1            | 2          | NULL              | prj1
        Index(
            "entity_slugs_unique_slugs_project_slugs",
            "namespace_id",
            "slug",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where="data_connector_id IS NULL",
        ),
        # NOTE: prevents 2 different data connectors owned by group or user from having the same slug
        # I.e. an invalid example like this:
        # namespace_id | project_id | data_connector_id | slug
        # 1            | NULL       | 1                 | dc1
        # 1            | NULL       | 2                 | dc1
        Index(
            "entity_slugs_unique_slugs_data_connector_in_group_user_slugs",
            "namespace_id",
            "data_connector_id",
            "slug",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where="project_id IS NULL",
        ),
        # NOTE: prevents 2 different data connectors owned by the same project from having the same slug
        # I.e. an invalid example like this:
        # namespace_id | project_id | data_connector_id | slug
        # 1            | 1          | 1                 | dc1
        # 1            | 1          | 2                 | dc1
        Index(
            "entity_slugs_unique_slugs_data_connector_in_project_slugs_1",
            "namespace_id",
            "project_id",
            "slug",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where="project_id IS NOT NULL AND data_connector_id IS NOT NULL",
        ),
        # NOTE: prevents the same data connector with the same slug being owned by different projects
        # I.e. an invalid example like this:
        # namespace_id | project_id | data_connector_id | slug
        # 1            | 1          | 1                 | dc1
        # 1            | 2          | 1                 | dc1
        Index(
            "entity_slugs_unique_slugs_data_connector_in_project_slugs_2",
            "namespace_id",
            "data_connector_id",
            "slug",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where="project_id IS NOT NULL AND data_connector_id IS NOT NULL",
        ),
        CheckConstraint(
            "(project_id IS NOT NULL) OR (data_connector_id IS NOT NULL)",
            name="one_or_both_project_id_or_group_id_are_set",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True, init=False)
    slug: Mapped[str] = mapped_column(String(99), index=True, nullable=False)
    project_id: Mapped[ULID | None] = mapped_column(
        ForeignKey(ProjectORM.id, ondelete="CASCADE", name="entity_slugs_project_id_fk"), index=True, nullable=True
    )
    project: Mapped[ProjectORM | None] = relationship(init=False, repr=False, back_populates="slug", lazy="selectin")
    data_connector_id: Mapped[ULID | None] = mapped_column(
        ForeignKey(DataConnectorORM.id, ondelete="CASCADE", name="entity_slugs_data_connector_id_fk"),
        index=True,
        nullable=True,
        unique=True,
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
    def create_data_connector_slug(
        cls,
        slug: str,
        data_connector_id: ULID,
        namespace_id: ULID,
        project_id: ULID | None = None,
    ) -> "EntitySlugORM":
        """Create an entity slug for a data connector."""
        return cls(
            slug=slug,
            project_id=project_id,
            data_connector_id=data_connector_id,
            namespace_id=namespace_id,
        )

    def dump_namespace(self) -> models.UserNamespace | models.GroupNamespace | models.ProjectNamespace:
        """Dump the entity slug as a namespace."""
        if self.project:
            return self.dump_project_namespace()
        return self.namespace.dump()

    def dump_project_namespace(self) -> models.ProjectNamespace:
        """Dump the entity slug as a namespace."""
        if not self.project:
            raise errors.ProgrammingError(
                message="Attempting to dump a namespace without a project as a project namespace"
            )
        return self.project.dump_as_namespace()


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
        index=True,
    )
    latest_slug: Mapped[EntitySlugORM] = relationship(lazy="joined", init=False, repr=False, viewonly=True)
    project_id: Mapped[ULID | None] = mapped_column(
        ForeignKey(ProjectORM.id, ondelete="CASCADE", name="entity_slugs_project_id_fk"), index=True, nullable=True
    )
    project: Mapped[ProjectORM | None] = relationship(init=False, repr=False, viewonly=True, default=None)
    data_connector_id: Mapped[ULID | None] = mapped_column(
        ForeignKey(DataConnectorORM.id, ondelete="CASCADE", name="entity_slugs_data_connector_id_fk"),
        index=True,
        nullable=True,
    )
    data_connector: Mapped[DataConnectorORM | None] = relationship(init=False, repr=False, viewonly=True, default=None)
