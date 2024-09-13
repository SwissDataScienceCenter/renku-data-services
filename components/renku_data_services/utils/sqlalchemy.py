"""Utilities for SQLAlchemy."""

from typing import cast

from sqlalchemy import Dialect, types
from ulid import ULID


class ULIDType(types.TypeDecorator):
    """Wrapper type for ULID <--> str conversion."""

    impl = types.String
    cache_ok = True

    def process_bind_param(self, value: ULID | None, dialect: Dialect) -> str | None:
        """Transform value for storing in the database."""
        if value is None:
            return None
        return str(value)

    def process_result_value(self, value: str | None, dialect: Dialect) -> ULID | None:
        """Transform string from database into ULID."""
        if value is None:
            return None
        return cast(ULID, ULID.from_str(value))  # cast because mypy doesn't understand ULID type annotations
