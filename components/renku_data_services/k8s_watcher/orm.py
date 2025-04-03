"""SQLAlchemy's schemas for the group database."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from box import Box
from sqlalchemy import JSON, DateTime, MetaData, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column
from ulid import ULID

from renku_data_services.base_orm.registry import COMMON_ORM_REGISTRY
from renku_data_services.k8s_watcher.models import ClusterId, K8sObject
from renku_data_services.utils.sqlalchemy import ULIDType

JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = MetaData(schema="common")
    registry = COMMON_ORM_REGISTRY


class K8sObjectORM(BaseORM):
    """Representation of a k8s resource."""

    __tablename__ = "k8s_objects"

    id: Mapped[ULID | None] = mapped_column(
        "id",
        ULIDType,
        primary_key=True,
        init=False,
        default=None,
        server_default="generate_ulid()",
    )
    name: Mapped[str] = mapped_column("name", String(), index=True)
    namespace: Mapped[str] = mapped_column("namespace", String(), index=True)
    creation_date: Mapped[datetime | None] = mapped_column(
        "creation_date",
        DateTime(timezone=True),
        server_default=func.now(),
        init=False,
        default=None,
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        "updated_at",
        DateTime(timezone=True),
        server_default=func.now(),
        server_onupdate=func.now(),
        init=False,
        default=None,
    )
    manifest: Mapped[dict[str, Any]] = mapped_column("manifest", JSONVariant)
    deleted: Mapped[bool] = mapped_column(default=False, init=False, index=True)
    version: Mapped[str] = mapped_column(index=True)
    kind: Mapped[str] = mapped_column(index=True)
    cluster: Mapped[str] = mapped_column(index=True)
    user_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)

    def dump(self) -> K8sObject:
        """Convert to a k8s object."""
        return K8sObject(
            name=self.name,
            namespace=self.namespace,
            cluster=ClusterId(self.cluster),
            kind=self.kind,
            version=self.version,
            manifest=Box(self.manifest),
            user_id=self.user_id,
        )
