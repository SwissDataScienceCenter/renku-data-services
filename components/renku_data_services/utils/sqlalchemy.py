"""Utilities for SQLAlchemy."""

from pathlib import PurePosixPath
from typing import cast

import asyncpg
from sqlalchemy import Dialect, types
from ulid import ULID

from renku_data_services.resource_usage.model import ComputeCapacity, Credit, DataSize


def get_postgres_error_code(exception: Exception) -> str | None:
    """Traverse exceptions to find and return the SQLSTATE error code.

    sqlalchemy hides the underlying database error in multiple layers
    of exceptions, making it not so straight forward to reach. This
    method is a helper to retrieve the postgresql error code which
    exactly defines the error situation.
    """
    exc: BaseException | None = exception
    while exc:
        if isinstance(exc, asyncpg.PostgresError):
            # impl note: this attribute is dynamic so there is no way to find it's definition
            # the documentation shows that it is available.
            return cast(str | None, exc.sqlstate)
        exc = exc.__cause__
    return None


class CreditType(types.TypeDecorator):
    """Convert Credit values to/from db."""

    impl = types.Integer
    cache_ok = True

    def process_bind_param(self, value: Credit | None, dialect: Dialect) -> int | None:
        """Transform to int."""
        return value.value if value is not None else None

    def process_result_value(self, value: int | None, dialect: Dialect) -> Credit | None:
        """Transform into Credit."""
        return Credit.from_int(value) if value is not None else None

    def process_literal_param(self, value: Credit | None, dialect: Dialect) -> str:
        """Return literal."""
        return str(value) if value is not None else ""


class ComputeCapacityType(types.TypeDecorator):
    """Convert ComputeCapacity values to/from db."""

    impl = types.Float

    def process_bind_param(self, value: ComputeCapacity | None, dialect: Dialect) -> float | None:
        """Transform value into a float."""
        if value is None:
            return None
        return value.cores

    def process_result_value(self, value: float | None, dialect: Dialect) -> ComputeCapacity | None:
        """Transform a float into ComputeCapacity value."""
        if value is None:
            return None
        return ComputeCapacity.from_cores(value)

    def process_literal_param(self, value: ComputeCapacity | None, dialect: Dialect) -> str:
        """Return a literal representation."""
        return str(value) if value is not None else ""


class DataSizeType(types.TypeDecorator):
    """Convert DataSize values to/from db."""

    impl = types.Float

    def process_bind_param(self, value: DataSize | None, dialect: Dialect) -> float | None:
        """Convert to db value."""
        return value.bytes if value is not None else None

    def process_result_value(self, value: float | None, dialect: Dialect) -> DataSize | None:
        """Convert to DataSize value."""
        return DataSize.from_bytes(value) if value is not None else None

    def process_literal_param(self, value: DataSize | None, dialect: Dialect) -> str:
        """Convert to literal."""
        return str(value) if value is not None else ""


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


class PurePosixPathType(types.TypeDecorator):
    """Wrapper type for Path <--> str conversion."""

    impl = types.String
    cache_ok = True

    def process_bind_param(self, value: PurePosixPath | str | None, dialect: Dialect) -> str | None:
        """Transform value for storing in the database."""
        if value is None:
            return None
        elif isinstance(value, str):
            return value
        else:
            return value.as_posix()

    def process_result_value(self, value: str | None, dialect: Dialect) -> PurePosixPath | None:
        """Transform string from database into PosixPath."""
        if value is None:
            return None
        return PurePosixPath(value)
