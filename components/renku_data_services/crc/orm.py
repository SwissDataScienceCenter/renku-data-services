"""SQLAlchemy schemas for the CRC database."""

import logging
from typing import Optional

from sqlalchemy import BigInteger, Column, Identity, Integer, MetaData, String, Table
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column, relationship
from sqlalchemy.schema import ForeignKey

import renku_data_services.base_models as base_models
from renku_data_services.crc import models
from renku_data_services.errors import errors

metadata_obj = MetaData(schema="resource_pools")  # Has to match alembic ini section name


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = metadata_obj


# This table indicates which users have access to which resource pools
# An entry in the table indicates that the user can access that resource pool.
resource_pools_users = Table(
    "resource_pools_users",
    BaseORM.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True),
    Column("resource_pool_id", ForeignKey("resource_pools.id", ondelete="CASCADE"), primary_key=True, index=True),
)


class RPUserORM(BaseORM):
    """Stores the Keycloak user ID for controlling user access to resource pools.

    Used in combination with the `resource_pool_users` table this table provides information
    about which user ID (based on Keycloak IDs) has access to which resource pools.
    In addition this table stores the indication of whether a specific user is expressly
    prohibited from accessing the default resource pool. If a user cannot access the default
    resource pool, the no_default_access field in this table for the specific user is set to true.
    """

    __tablename__ = "users"
    keycloak_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    no_default_access: Mapped[bool] = mapped_column(default=False, insert_default=False)
    resource_pools: Mapped[list["ResourcePoolORM"]] = relationship(
        secondary=resource_pools_users,
        back_populates="users",
        default_factory=list,
        cascade="save-update, merge, delete",
    )
    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True, init=False)

    @classmethod
    def load(cls, user: base_models.User) -> "RPUserORM":
        """Create an ORM object from a user model."""
        return cls(keycloak_id=user.keycloak_id, no_default_access=user.no_default_access)

    def dump(self) -> base_models.User:
        """Create a user model from the ORM object."""
        return base_models.User(id=self.id, keycloak_id=self.keycloak_id, no_default_access=self.no_default_access)


class ResourceClassORM(BaseORM):
    """Resource class specifies a set of resources that can be used in a session."""

    __tablename__ = "resource_classes"
    name: Mapped[str] = mapped_column("name", String(40), index=True)
    cpu: Mapped[float] = mapped_column()
    memory: Mapped[int] = mapped_column(BigInteger)
    max_storage: Mapped[int] = mapped_column(BigInteger)
    default_storage: Mapped[int] = mapped_column(BigInteger)
    default: Mapped[bool] = mapped_column(default=False)
    gpu: Mapped[int] = mapped_column(BigInteger, default=0)
    resource_pool_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("resource_pools.id", ondelete="CASCADE"), default=None, index=True
    )
    resource_pool: Mapped[Optional["ResourcePoolORM"]] = relationship(back_populates="classes", default=None)
    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True, default=None, init=False)
    tolerations: Mapped[list["TolerationORM"]] = relationship(
        back_populates="resource_class",
        default_factory=list,
        cascade="save-update, merge, delete",
        lazy="selectin",
    )
    node_affinities: Mapped[list["NodeAffintyORM"]] = relationship(
        back_populates="resource_class",
        default_factory=list,
        cascade="save-update, merge, delete",
        lazy="selectin",
    )

    @classmethod
    def load(cls, resource_class: models.ResourceClass) -> "ResourceClassORM":
        """Create a ORM object from the resource class model."""
        return cls(
            name=resource_class.name,
            cpu=resource_class.cpu,
            memory=resource_class.memory,
            max_storage=resource_class.max_storage,
            gpu=resource_class.gpu,
            default=resource_class.default,
            default_storage=resource_class.default_storage,
            node_affinities=[NodeAffintyORM.load(affinity) for affinity in resource_class.node_affinities],
            tolerations=[TolerationORM(key=toleration) for toleration in resource_class.tolerations],
        )

    def dump(self, matching_criteria: models.ResourceClass | None = None) -> models.ResourceClass:
        """Create a resource class model from the ORM object."""
        matching: bool | None = None
        if matching_criteria:
            matching = (
                self.cpu >= matching_criteria.cpu
                and self.memory >= matching_criteria.memory
                and self.gpu >= matching_criteria.gpu
                and self.max_storage >= matching_criteria.max_storage
            )
        return models.ResourceClass(
            id=self.id,
            name=self.name,
            cpu=self.cpu,
            memory=self.memory,
            max_storage=self.max_storage,
            gpu=self.gpu,
            default=self.default,
            default_storage=self.default_storage,
            node_affinities=[affinity.dump() for affinity in self.node_affinities],
            tolerations=[toleration.key for toleration in self.tolerations],
            matching=matching,
        )


class ResourcePoolORM(BaseORM):
    """Resource pool specifies a set of resource classes, users that can access them and a quota."""

    __tablename__ = "resource_pools"
    name: Mapped[str] = mapped_column(String(40), index=True)
    quota: Mapped[Optional[str]] = mapped_column(String(63), index=True, default=None)
    users: Mapped[list["RPUserORM"]] = relationship(
        secondary=resource_pools_users, back_populates="resource_pools", default_factory=list
    )
    classes: Mapped[list["ResourceClassORM"]] = relationship(
        back_populates="resource_pool",
        default_factory=list,
        cascade="save-update, merge, delete",
        lazy="selectin",
        order_by=(
            "[ResourceClassORM.gpu,ResourceClassORM.cpu,ResourceClassORM.memory,ResourceClassORM.max_storage,"
            "ResourceClassORM.name,ResourceClassORM.id]"
        ),
    )
    idle_threshold: Mapped[Optional[int]] = mapped_column(default=None)
    hibernation_threshold: Mapped[Optional[int]] = mapped_column(default=None)
    default: Mapped[bool] = mapped_column(default=False, index=True)
    public: Mapped[bool] = mapped_column(default=False, index=True)
    id: Mapped[int] = mapped_column("id", Integer, Identity(always=True), primary_key=True, default=None, init=False)

    @classmethod
    def load(cls, resource_pool: models.ResourcePool) -> "ResourcePoolORM":
        """Create an ORM object from the resource pool model."""
        quota = None
        if isinstance(resource_pool.quota, models.Quota):
            quota = resource_pool.quota.id
        return cls(
            name=resource_pool.name,
            quota=quota,
            classes=[ResourceClassORM.load(resource_class) for resource_class in resource_pool.classes],
            idle_threshold=resource_pool.idle_threshold,
            hibernation_threshold=resource_pool.hibernation_threshold,
            public=resource_pool.public,
            default=resource_pool.default,
        )

    def dump(
        self, quota: models.Quota | None, class_match_criteria: models.ResourceClass | None = None
    ) -> models.ResourcePool:
        """Create a resource pool model from the ORM object and a quota."""
        classes: list[ResourceClassORM] = self.classes
        if quota and quota.id != self.quota:
            raise errors.BaseError(
                message="Unexpected error when dumping a resource pool ORM.",
                detail=f"The quota name in the database {self.quota} and Kubernetes {quota.id} do not match.",
            )
        if (quota is None and self.quota is not None) or (quota is not None and self.quota is None):
            logging.error(
                f"Unexpected error when dumping resource pool ORM with ID {self.id}. "
                f"The quota in the database {self.quota} and Kubernetes {quota} do not match. "
                f"Using the quota {quota} in the response."
            )
        return models.ResourcePool(
            id=self.id,
            name=self.name,
            quota=quota,
            classes=[resource_class.dump(class_match_criteria) for resource_class in classes],
            idle_threshold=self.idle_threshold,
            hibernation_threshold=self.hibernation_threshold,
            public=self.public,
            default=self.default,
        )


class TolerationORM(BaseORM):
    """The key for a K8s toleration used to schedule loads on tainted nodes."""

    __tablename__ = "tolerations"
    key: Mapped[str] = mapped_column(String(63), index=True)
    resource_class: Mapped[Optional["ResourceClassORM"]] = relationship(
        back_populates="tolerations", default=None, lazy="selectin"
    )
    resource_class_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("resource_classes.id"), default=None, index=True
    )
    id: Mapped[int] = mapped_column("id", Integer, Identity(always=True), primary_key=True, default=None, init=False)


class NodeAffintyORM(BaseORM):
    """The key for a K8s node label used to schedule loads specific nodes."""

    __tablename__ = "node_affinities"
    key: Mapped[str] = mapped_column(String(63), index=True)
    resource_class: Mapped[Optional["ResourceClassORM"]] = relationship(
        back_populates="node_affinities", default=None, lazy="selectin"
    )
    resource_class_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("resource_classes.id"), default=None, index=True
    )
    required_during_scheduling: Mapped[bool] = mapped_column(default=False)
    id: Mapped[int] = mapped_column("id", Integer, Identity(always=True), primary_key=True, default=None, init=False)

    @classmethod
    def load(cls, affinity: models.NodeAffinity) -> "NodeAffintyORM":
        """Create an ORM object from the node affinity model."""
        return cls(
            key=affinity.key,
            required_during_scheduling=affinity.required_during_scheduling,
        )

    def dump(self) -> models.NodeAffinity:
        """Create a node affinity model from the ORM object."""
        return models.NodeAffinity(
            key=self.key,
            required_during_scheduling=self.required_during_scheduling,
        )
