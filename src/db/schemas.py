"""SQLAlchemy schemas for the database."""
from typing import List, Optional

from sqlalchemy import BigInteger, Column, Integer, String, Table
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column, relationship
from sqlalchemy.schema import ForeignKey

import models


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    pass


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
    def load(cls, user: models.User):
        """Create an ORM object from a user model."""
        return cls(keycloak_id=user.keycloak_id)

    def dump(self) -> models.User:
        """Create a user model from the ORM object."""
        return models.User(id=self.id, keycloak_id=self.keycloak_id)


class QuotaORM(BaseORM):
    """Quota for resource usage."""

    __tablename__ = "quotas"
    cpu: Mapped[float] = mapped_column()
    memory: Mapped[int] = mapped_column(BigInteger)
    storage: Mapped[int] = mapped_column(BigInteger)
    gpu: Mapped[int] = mapped_column(BigInteger, default=0)
    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    resource_pool_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("resource_pools.id", ondelete="CASCADE"),
        unique=True,
        default=None,
        index=True,
    )
    resource_pool: Mapped[Optional["ResourcePoolORM"]] = relationship(back_populates="quota", default=None)

    @classmethod
    def load(cls, quota: Optional[models.Quota]):
        """Create an ORM object from a quota model."""
        if quota is None:
            return None
        return cls(
            cpu=quota.cpu,
            memory=quota.memory,
            storage=quota.storage,
            gpu=quota.gpu,
        )

    def dump(self) -> models.Quota:
        """Create a quota model from the ORM object."""
        return models.Quota(id=self.id, cpu=self.cpu, memory=self.memory, storage=self.storage, gpu=self.gpu)


class ResourceClassORM(BaseORM):
    """Resource class specifies a set of resources that can be used in a session."""

    __tablename__ = "resource_classes"
    name: Mapped[str] = mapped_column("name", String(40), index=True)
    cpu: Mapped[float] = mapped_column()
    memory: Mapped[int] = mapped_column(BigInteger)
    max_storage: Mapped[int] = mapped_column(BigInteger)
    default: Mapped[bool] = mapped_column(default=False)
    gpu: Mapped[int] = mapped_column(BigInteger, default=0)
    resource_pool_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("resource_pools.id", ondelete="CASCADE"), default=None, index=True
    )
    resource_pool: Mapped[Optional["ResourcePoolORM"]] = relationship(back_populates="classes", default=None)
    id: Mapped[int] = mapped_column(primary_key=True, default=None, init=False)

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
        )


class ResourcePoolORM(BaseORM):
    """Resource pool specifies a set of resource classes, users that can access them and a quota."""

    __tablename__ = "resource_pools"
    name: Mapped[str] = mapped_column(String(40), index=True)
    quota: Mapped[Optional["QuotaORM"]] = relationship(
        back_populates="resource_pool",
        default=None,
        cascade="save-update, merge, delete",
    )
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
        return cls(
            name=resource_pool.name,
            quota=QuotaORM.load(resource_pool.quota),
            classes=[ResourceClassORM.load(resource_class) for resource_class in resource_pool.classes],
            public=resource_pool.public,
            default=resource_pool.default,
        )

    def dump(self) -> models.ResourcePool:
        """Create a resource pool model from the ORM object."""
        quota: Optional[QuotaORM] = self.quota
        classes: List[ResourceClassORM] = self.classes
        return models.ResourcePool(
            id=self.id,
            name=self.name,
            quota=None if not quota else quota.dump(),
            classes={resource_class.dump() for resource_class in classes},
            public=self.public,
            default=self.default,
        )
