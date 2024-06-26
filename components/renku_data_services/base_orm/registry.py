"""Common SqlAlchemy registry for all ORM definitions."""

from sqlalchemy.orm import DeclarativeBase


class _CommonBaseWithRegistry(DeclarativeBase):
    pass


COMMON_ORM_REGISTRY = _CommonBaseWithRegistry.registry
"""Common SqlAlchemy registry for all ORM definitions."""
