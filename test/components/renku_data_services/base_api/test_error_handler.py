"""Test functions for the error_handler module."""

from sqlite3 import Error as SqliteError

import httpx
import jwt
from asyncpg.exceptions import PostgresError
from pydantic import ValidationError as PydanticValidationError
from sanic import SanicException
from sanic_ext.exceptions import ValidationError as SanicValidationError
from sqlalchemy.exc import SQLAlchemyError

from renku_data_services.base_api.error_handler import CustomErrorHandler
from renku_data_services.errors import errors


def make_sqlite_error() -> SqliteError:
    err = SqliteError()
    err.sqlite_errorcode = 1
    err.sqlite_errorname = "name"
    return err


def make_pg_error() -> PostgresError:
    err = PostgresError()
    err.msg = "not supported"
    err.pgcode = "A0110"
    return err


def test_match_exception() -> None:
    expect_to_match = [
        errors.BaseError(),
        SanicValidationError(extra={"exception": PydanticValidationError("oops", [])}),
        SanicValidationError(extra={"exception": TypeError("oops")}),
        PydanticValidationError("oops", []),
        SanicException(),
        make_sqlite_error(),
        make_pg_error(),
        SQLAlchemyError(),
        OverflowError(),
        jwt.exceptions.InvalidTokenError(),
        httpx.ConnectError("oops"),
        httpx.UnsupportedProtocol("ftp"),
    ]

    for exc in expect_to_match:
        result = CustomErrorHandler._get_formatted_exception(exc)
        assert result is not None
