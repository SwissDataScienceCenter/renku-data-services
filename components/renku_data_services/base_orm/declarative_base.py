"""Declarative base class for all ORM definitions."""

from sqlalchemy.orm import DeclarativeBase


class CustomBase(DeclarativeBase):
    """Base class for all ORM classes."""
