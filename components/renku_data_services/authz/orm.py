"""SQLAlchemy schemas for the CRC database."""

from typing import Optional

from sqlalchemy import MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = MetaData(schema="authz")  # Has to match alembic ini section name


class ProjectUserAuthz(BaseORM):
    """Projects authorization table."""

    __tablename__ = "project_user_authz"
    project_id: Mapped[str] = mapped_column("project_id", String(26), index=True)
    role: Mapped[int] = mapped_column(index=True)
    user_id: Mapped[Optional[str]] = mapped_column("user_id", String(36), index=True, default=None)
    id: Mapped[int] = mapped_column(primary_key=True, default=None, init=False)
