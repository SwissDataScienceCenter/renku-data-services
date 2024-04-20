"""Fixtures for testing."""

import os
import subprocess
from collections.abc import Iterator

import pytest
from hypothesis import settings
from pytest_postgresql import factories
from pytest_postgresql.janitor import DatabaseJanitor

import renku_data_services.base_models as base_models
from renku_data_services.app_config import Config as DataConfig
from renku_data_services.authz.config import AuthzConfig
from renku_data_services.db_config.config import DBConfig
from renku_data_services.migrations.core import run_migrations_for_app
from ulid import ULID

settings.register_profile("ci", deadline=400, max_examples=5)
settings.register_profile("dev", deadline=200, max_examples=5)

settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "dev"))


@pytest.fixture
def authz_config(monkeypatch) -> Iterator[AuthzConfig]:
    port = 60051
    proc = subprocess.Popen(["spicedb", "serve-testing", "--grpc-addr", f":{port}"])
    monkeypatch.setenv("AUTHZ_DB_HOST", "127.0.0.1")
    # NOTE: In our devcontainer setup 50051 and 50052 is taken by the running authzed instance
    monkeypatch.setenv("AUTHZ_DB_GRPC_PORT", f"{port}")
    monkeypatch.setenv("AUTHZ_DB_KEY", "renku")
    yield AuthzConfig.from_env()
    try:
        proc.terminate()
    except Exception:
        proc.kill()


def init_db(**kwargs):
    """Run database migrations so they don't need to run on every test."""
    dummy_stores = os.environ.get("DUMMY_STORES")
    name = os.environ.get("DB_NAME")
    user = os.environ.get("DB_USER")
    pw = os.environ.get("DB_PASSWORD")
    host = os.environ.get("DB_HOST")
    port = os.environ.get("DB_PORT")

    os.environ["DUMMY_STORES"] = "true"
    os.environ["DB_NAME"] = kwargs["dbname"]
    os.environ["DB_USER"] = kwargs["user"]
    os.environ["DB_PASSWORD"] = kwargs["password"]
    os.environ["DB_HOST"] = kwargs["host"]
    os.environ["DB_PORT"] = str(kwargs["port"])

    run_migrations_for_app("common")

    if dummy_stores:
        os.environ["DUMMY_STORES"] = dummy_stores
    else:
        del os.environ["DUMMY_STORES"]
    if name:
        os.environ["DB_NAME"] = name
    else:
        del os.environ["DB_NAME"]
    if user:
        os.environ["DB_USER"] = user
    else:
        del os.environ["DB_USER"]
    if pw:
        os.environ["DB_PASSWORD"] = pw
    else:
        del os.environ["DB_PASSWORD"]
    if host:
        os.environ["DB_HOST"] = host
    else:
        del os.environ["DB_HOST"]
    if port:
        os.environ["DB_PORT"] = port
    else:
        del os.environ["DB_PORT"]


postgresql_in_docker = factories.postgresql_noproc(load=[init_db])
postgresql = factories.postgresql("postgresql_in_docker")

@pytest.fixture
def db_config(monkeypatch) -> Iterator[DBConfig]:
    db_name = str(ULID()).lower()
    user = "renku"
    host = "127.0.0.1"
    port = 5432
    password = "renku"

    monkeypatch.setenv("DUMMY_STORES", "true")
    monkeypatch.setenv("DB_NAME", db_name)
    monkeypatch.setenv("DB_USER", user)
    monkeypatch.setenv("DB_PASSWORD", password)
    monkeypatch.setenv("DB_HOST", host)
    monkeypatch.setenv("DB_PORT", port)
    with DatabaseJanitor(
        user, host, port, db_name, "16.2", password,
    ):
        yield DBConfig.from_env()

@pytest.fixture
def run_migrations(db_config, authz_config):
    run_migrations_for_app("common")

@pytest.fixture
def app_config(run_migrations, monkeypatch) -> Iterator[DataConfig]:
    monkeypatch.setenv("MAX_PINNED_PROJECTS", "5")

    config = DataConfig.from_env()
    yield config
    monkeypatch.delenv("DUMMY_STORES", raising=False)
    # NOTE: This is necessary because the postgresql pytest extension does not close
    # the async connection/pool we use in the config and the connection will succeed in the first
    # test but fail in all others if the connection is not disposed at the end of every test.
    config.db.dispose_connection()


@pytest.fixture
def admin_user() -> base_models.APIUser:
    return base_models.APIUser(
        is_admin=True,
        id="some-random-id-123456",
        access_token="some-access-token",
        full_name="Admin Adminson",
        first_name="Admin",
        last_name="Adminson",
        email="admin@gmail.com",
    )  # nosec B106


@pytest.fixture
def loggedin_user() -> base_models.APIUser:
    return base_models.APIUser(is_admin=False, id="some-random-id-123456", access_token="some-access-token")  # nosec B106


def only(iterable, default=None, too_long=None):
    """From https://github.com/python/importlib_resources/blob/v5.13.0/importlib_resources/_itertools.py#L2."""
    it = iter(iterable)
    first_value = next(it, default)

    try:
        second_value = next(it)
    except StopIteration:
        pass
    else:
        msg = f"Expected exactly one item in iterable, but got {first_value!r}, {second_value!r}, and perhaps more."
        raise too_long or ValueError(msg)

    return first_value
