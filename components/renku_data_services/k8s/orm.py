"""SQLAlchemy's schemas for the group database."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from box import Box
from sqlalchemy import ColumnElement, DateTime, MetaData, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import Comparator, hybrid_property
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column
from ulid import ULID

from renku_data_services.base_orm.registry import COMMON_ORM_REGISTRY
from renku_data_services.errors import errors
from renku_data_services.k8s.constants import ClusterId
from renku_data_services.k8s.models import GVK, K8sObject
from renku_data_services.utils.sqlalchemy import ULIDType


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = MetaData(schema="common")
    registry = COMMON_ORM_REGISTRY


class CaseInsensitiveComparator(Comparator[str]):
    """Enables case insensitive comparison of strings.

    See https://docs.sqlalchemy.org/en/20/orm/extensions/hybrid.html#building-custom-comparators.
    """

    def __eq__(self, other: Any) -> ColumnElement[bool]:  # type: ignore[override]
        return func.lower(self.__clause_element__()) == func.lower(other)


class CaseInsensitiveNullableComparator(Comparator[str | None]):
    """Enables case insensitive comparison of nullable string fields."""

    def __eq__(self, other: Any) -> ColumnElement[bool]:  # type: ignore[override]
        return func.lower(self.__clause_element__()) == func.lower(other)


class K8sObjectORM(BaseORM):
    """Representation of a k8s resource."""

    __tablename__ = "k8s_objects"
    __table_args__ = (
        UniqueConstraint(
            "group",
            "version",
            "kind",
            "cluster",
            "namespace",
            "name",
            name="_unique_common_k8s_objects_gvk_cluster_namespace_name",
        ),
    )

    id: Mapped[ULID] = mapped_column(
        "id",
        ULIDType,
        primary_key=True,
        init=False,
        default_factory=lambda: str(ULID()),
        server_default=text("generate_ulid()"),
    )
    name: Mapped[str] = mapped_column("name", String(), index=True)
    namespace: Mapped[str] = mapped_column("namespace", String(), index=True)
    creation_date: Mapped[datetime] = mapped_column(
        "creation_date",
        DateTime(timezone=True),
        server_default=func.now(),
        init=False,
        default=None,
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updated_at",
        DateTime(timezone=True),
        server_default=func.now(),
        server_onupdate=func.now(),
        init=False,
        default=None,
    )
    manifest: Mapped[dict[str, Any]] = mapped_column("manifest", JSONB)
    deleted: Mapped[bool] = mapped_column(default=False, init=False, index=True)
    group: Mapped[str | None] = mapped_column(index=True, nullable=True)
    version: Mapped[str] = mapped_column(index=True)
    kind: Mapped[str] = mapped_column(index=True)
    cluster: Mapped[ULID] = mapped_column(ULIDType, index=True)
    user_id: Mapped[str] = mapped_column(String(), index=True)

    @hybrid_property
    def group_insensitive(self) -> str | None:
        """Case insensitive version of group."""
        if self.group:
            return self.group.lower()
        return None

    @hybrid_property
    def kind_insensitive(self) -> str:
        """Case insensitive version of kind."""
        return self.kind.lower()

    @hybrid_property
    def version_insensitive(self) -> str:
        """Case insensitive version of version."""
        return self.version.lower()

    @group_insensitive.inplace.comparator
    @classmethod
    def _group_insensitive_comparator(cls) -> CaseInsensitiveNullableComparator:
        if cls.group is None:
            raise errors.ProgrammingError(message="Cannot compare group with = if group is None")
        return CaseInsensitiveNullableComparator(cls.group)

    @kind_insensitive.inplace.comparator
    @classmethod
    def _kind_insensitive_comparator(cls) -> CaseInsensitiveComparator:
        return CaseInsensitiveComparator(cls.kind)

    @version_insensitive.inplace.comparator
    @classmethod
    def _version_insensitive_comparator(cls) -> CaseInsensitiveComparator:
        return CaseInsensitiveComparator(cls.version)

    def dump(self) -> K8sObject:
        """Convert to a k8s object."""
        return K8sObject(
            name=self.name,
            namespace=self.namespace,
            cluster=ClusterId(self.cluster),
            gvk=GVK(group=self.group, version=self.version, kind=self.kind),
            manifest=Box(self.manifest),
            user_id=self.user_id,
        )
