"""ORM classes."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import cast

from sqlalchemy import DateTime, Float, Integer, Interval, MetaData, String, text
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column
from ulid import ULID

from renku_data_services.resource_usage.model import ComputeCapacity, DataSize, ResourcesRequest
from renku_data_services.utils.sqlalchemy import ComputeCapacityType, DataSizeType, ULIDType


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = MetaData(schema="common")  # Has to match alembic ini section name


class ResourceRequestsLogORM(BaseORM):
    """Table for recording resource requests."""

    __tablename__ = "resource_requests_log"

    id: Mapped[ULID] = mapped_column(
        "id", ULIDType, primary_key=True, server_default=text("generate_ulid()"), init=False
    )
    """Artificial identifier with stable order."""

    cluster_id: Mapped[ULID | None] = mapped_column("cluster_id", ULIDType(), nullable=True)
    """The cluster id, may be null."""

    namespace: Mapped[str] = mapped_column("namespace", String(), nullable=False)
    """The cluster namespace."""

    name: Mapped[str] = mapped_column("name", String(), nullable=False)
    """The name of the pod."""

    uid: Mapped[str] = mapped_column("uid", String(), nullable=False)
    """The k8s uid of the pod."""

    kind: Mapped[str] = mapped_column("kind", String(), nullable=False)
    """The kind of the object: either pod or pvc."""

    api_version: Mapped[str] = mapped_column("api_version", String(), nullable=False)
    """The k8s apiVersion of the object."""

    phase: Mapped[str] = mapped_column("phase", String(), nullable=False)
    """The k8s uid of the pod."""

    capture_date: Mapped[datetime] = mapped_column("capture_date", DateTime(timezone=True), nullable=False)
    """The timestamp the values were captured."""

    capture_interval: Mapped[timedelta] = mapped_column("capture_interval", Interval(), nullable=False)
    """The configured capture interval for that point."""

    user_id: Mapped[str | None] = mapped_column("user_id", String(), nullable=True)
    """The user id associated to the request data."""

    project_id: Mapped[ULID | None] = mapped_column("project_id", ULIDType(), nullable=True)
    """A project id associated to the requests data."""

    launcher_id: Mapped[ULID | None] = mapped_column("launcher_id", ULIDType(), nullable=True)
    """The launcher id used to start the session."""

    resource_class_id: Mapped[int | None] = mapped_column("resource_class_id", Integer(), nullable=True)
    """The resource class id used to start the session."""

    resource_pool_id: Mapped[int | None] = mapped_column("resource_pool_id", Integer(), nullable=True)
    """The resource class id used to start the session."""

    since: Mapped[datetime | None] = mapped_column("since", DateTime(timezone=True), nullable=True)
    """The timestamp the object has been started (pod) or created (pvc)."""

    cpu_request: Mapped[ComputeCapacity | None] = mapped_column("cpu_request", ComputeCapacityType(), nullable=True)
    """The cpu request."""

    memory_request: Mapped[DataSize | None] = mapped_column("memory_request", DataSizeType(), nullable=True)
    """The memory request."""

    gpu_request: Mapped[ComputeCapacity | None] = mapped_column("gpu_request", ComputeCapacityType(), nullable=True)
    """The gpu request."""

    gpu_slice: Mapped[float | None] = mapped_column("gpu_slice", Float(), nullable=True)
    """The slice of the cpu provided."""

    disk_request: Mapped[DataSize | None] = mapped_column("disk_request", DataSizeType(), nullable=True)
    """The disk request."""

    @classmethod
    def from_resources_request(cls, req: ResourcesRequest) -> ResourceRequestsLogORM:
        """Create an ORM object given a ResourcesRequest."""
        return ResourceRequestsLogORM(
            cluster_id=cast(ULID, req.cluster_id) if req.cluster_id else None,
            namespace=req.namespace,
            name=req.name,
            uid=req.uid,
            kind=req.kind,
            api_version=req.api_version,
            phase=req.phase,
            capture_date=req.capture_date,
            capture_interval=req.capture_interval,
            user_id=req.user_id,
            project_id=req.project_id,
            launcher_id=req.launcher_id,
            resource_class_id=req.resource_class_id,
            resource_pool_id=req.resource_pool_id,
            since=req.since,
            cpu_request=req.data.cpu,
            memory_request=req.data.memory,
            gpu_request=req.data.gpu,
            gpu_slice=req.gpu_slice,
            disk_request=req.data.disk,
        )
