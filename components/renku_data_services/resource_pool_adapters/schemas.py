"""SQLAlchemy schemas for the CRC database."""
from typing import List, Optional

from sqlalchemy import BigInteger, Column, Integer, MetaData, String, Table
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column, relationship
from sqlalchemy.schema import ForeignKey

import renku_data_services.base_models as base_models
import renku_data_services.resource_pool_models as models

metadata_obj = MetaData(schema="resource_pools")  # Has to match alembic ini section name


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = metadata_obj


resource_pools_users = Table(
    "resource_pools_users",
    BaseORM.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True),
    Column("resource_pool_id", ForeignKey("resource_pools.id", ondelete="CASCADE"), primary_key=True, index=True),
)


class UserORM(BaseORM):
    """Stores the Keycloak user ID."""

    __tablename__ = "users"
    keycloak_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    resource_pools: Mapped[List["ResourcePoolORM"]] = relationship(
        secondary=resource_pools_users,
        back_populates="users",
        default_factory=list,
        cascade="save-update, merge, delete",
    )
    id: Mapped[int] = mapped_column(primary_key=True, init=False)

    @classmethod
    def load(cls, user: base_models.User):
        """Create an ORM object from a user model."""
        return cls(keycloak_id=user.keycloak_id)

    def dump(self) -> base_models.User:
        """Create a user model from the ORM object."""
        return base_models.User(id=self.id, keycloak_id=self.keycloak_id)


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
    id: Mapped[int] = mapped_column(primary_key=True, default=None, init=False)
    tolerations: Mapped[List["TolerationORM"]] = relationship(
        back_populates="resource_class",
        default_factory=list,
        cascade="save-update, merge, delete",
        lazy="selectin",
    )
    node_affinities: Mapped[List["NodeAffintyORM"]] = relationship(
        back_populates="resource_class",
        default_factory=list,
        cascade="save-update, merge, delete",
        lazy="selectin",
    )

    @classmethod
    def load(cls, resource_class: models.ResourceClass):
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

    def dump(self) -> models.ResourceClass:
        """Create a resource class model from the ORM object."""
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
        )


class ResourcePoolORM(BaseORM):
    """Resource pool specifies a set of resource classes, users that can access them and a quota."""

    __tablename__ = "resource_pools"
    name: Mapped[str] = mapped_column(String(40), index=True)
    quota: Mapped[Optional[str]] = mapped_column(String(63), index=True, default=None)
    users: Mapped[List["UserORM"]] = relationship(
        secondary=resource_pools_users, back_populates="resource_pools", default_factory=list
    )
    classes: Mapped[List["ResourceClassORM"]] = relationship(
        back_populates="resource_pool",
        default_factory=list,
        cascade="save-update, merge, delete",
    )
    default: Mapped[bool] = mapped_column(default=False, index=True)
    public: Mapped[bool] = mapped_column(default=False, index=True)
    id: Mapped[int] = mapped_column("id", Integer, primary_key=True, default=None, init=False)

    @classmethod
    def load(cls, resource_pool: models.ResourcePool):
        """Create an ORM object from the resource pool model."""
        quota = None
        if isinstance(resource_pool.quota, str):
            quota = resource_pool.quota
        elif isinstance(resource_pool.quota, models.Quota):
            quota = resource_pool.quota.id
        return cls(
            name=resource_pool.name,
            quota=quota,  # type: ignore[arg-type]
            classes=[ResourceClassORM.load(resource_class) for resource_class in resource_pool.classes],
            public=resource_pool.public,
            default=resource_pool.default,
        )

    def dump(self) -> models.ResourcePool:
        """Create a resource pool model from the ORM object."""
        classes: List[ResourceClassORM] = self.classes
        return models.ResourcePool(
            id=self.id,
            name=self.name,
            quota=self.quota,
            classes=[resource_class.dump() for resource_class in classes],
            public=self.public,
            default=self.default,
        )


class TolerationORM(BaseORM):
    """The key for a K8s toleration used to schedule loads on tainted nodes."""

    __tablename__ = "tolerations"
    key: Mapped[str] = mapped_column(String(63))
    resource_class: Mapped[Optional["ResourceClassORM"]] = relationship(back_populates="tolerations", default=None)
    resource_class_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("resource_classes.id"), default=None, index=True
    )
    id: Mapped[int] = mapped_column("id", Integer, primary_key=True, default=None, init=False)


class NodeAffintyORM(BaseORM):
    """The key for a K8s node label used to schedule loads specific nodes."""

    __tablename__ = "node_affinities"
    key: Mapped[str] = mapped_column(String(63))
    resource_class: Mapped[Optional["ResourceClassORM"]] = relationship(back_populates="node_affinities", default=None)
    resource_class_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("resource_classes.id"), default=None, index=True
    )
    required_during_scheduling: Mapped[bool] = mapped_column(default=False)
    id: Mapped[int] = mapped_column("id", Integer, primary_key=True, default=None, init=False)

    @classmethod
    def load(cls, affinity: models.NodeAffinity):
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
