"""ORM classes."""

from datetime import datetime

from sqlalchemy import DateTime, MetaData, String, text
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column
from sqlalchemy.types import Float
from ulid import ULID

from renku_data_services.utils.sqlalchemy import ULIDType


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

    cluster_id: Mapped[ULID | None] = mapped_column("cluster_id", String(), nullable=True)
    """The cluster id, may be null."""

    namespace: Mapped[str] = mapped_column("namespace", String(), nullable=False)
    """The cluster namespace."""

    pod_name: Mapped[str] = mapped_column("pod_name", String(), nullable=False)
    """The name of the pod."""

    capture_date: Mapped[datetime] = mapped_column("capture_date", DateTime(timezone=True), nullable=False)
    """The timestamp the values were captured."""

    user_id: Mapped[str | None] = mapped_column("user_id", String(), nullable=True)

    project_id: Mapped[ULID | None] = mapped_column("project_id", ULIDType(), nullable=True)

    launcher_id: Mapped[ULID | None] = mapped_column("launcher_id", ULIDType(), nullable=True)

    cpu_request: Mapped[float] = mapped_column("cpu_request", Float(), nullable=False)

    memory_request: Mapped[float] = mapped_column("memory_request", Float(), nullable=False)

    gpu_request: Mapped[float] = mapped_column("gpu_request", Float(), nullable=False)
