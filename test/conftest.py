"""Fixtures for testing."""

from pathlib import Path

import pytest

import renku_data_services.base_models as base_models
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.resource_pool_adapters import ResourcePoolRepository, UserRepository
from renku_data_services.storage_adapters import StorageRepository


@pytest.fixture
def sqlite_file_url_async(tmp_path: Path):
    db = tmp_path / "sqlite.db"
    db.touch()
    yield f"sqlite+aiosqlite:///{db.absolute().resolve()}"
    db.unlink(missing_ok=True)


@pytest.fixture
def sqlite_file_url_sync(tmp_path: Path):
    db = tmp_path / "sqlite.db"
    db.touch()
    yield f"sqlite:///{db.absolute().resolve()}"
    db.unlink(missing_ok=True)


@pytest.fixture
def user_repo(sqlite_file_url_sync, sqlite_file_url_async, monkeypatch):
    db = UserRepository(sqlite_file_url_sync, sqlite_file_url_async)
    monkeypatch.setenv("ASYNC_SQLALCHEMY_URL", sqlite_file_url_async)
    monkeypatch.setenv("SYNC_SQLALCHEMY_URL", sqlite_file_url_sync)
    monkeypatch.setenv("DUMMY_STORES", "true")
    run_migrations_for_app("resource_pools", db)
    monkeypatch.delenv("ASYNC_SQLALCHEMY_URL")
    monkeypatch.delenv("SYNC_SQLALCHEMY_URL")
    monkeypatch.delenv("DUMMY_STORES")
    yield db
    monkeypatch.delenv("ASYNC_SQLALCHEMY_URL", raising=False)
    monkeypatch.delenv("SYNC_SQLALCHEMY_URL", raising=False)
    monkeypatch.delenv("DUMMY_STORES", raising=False)


@pytest.fixture
def pool_repo(sqlite_file_url_sync, sqlite_file_url_async, monkeypatch):
    db = ResourcePoolRepository(sqlite_file_url_sync, sqlite_file_url_async)
    monkeypatch.setenv("ASYNC_SQLALCHEMY_URL", sqlite_file_url_async)
    monkeypatch.setenv("SYNC_SQLALCHEMY_URL", sqlite_file_url_sync)
    monkeypatch.setenv("DUMMY_STORES", "true")
    run_migrations_for_app("resource_pools", db)
    monkeypatch.delenv("ASYNC_SQLALCHEMY_URL")
    monkeypatch.delenv("SYNC_SQLALCHEMY_URL")
    monkeypatch.delenv("DUMMY_STORES")
    yield db
    monkeypatch.delenv("ASYNC_SQLALCHEMY_URL", raising=False)
    monkeypatch.delenv("SYNC_SQLALCHEMY_URL", raising=False)
    monkeypatch.delenv("DUMMY_STORES", raising=False)


@pytest.fixture
def storage_repo(sqlite_file_url_sync, sqlite_file_url_async, monkeypatch):
    db = StorageRepository(sqlite_file_url_sync, sqlite_file_url_async)
    monkeypatch.setenv("ASYNC_SQLALCHEMY_URL", sqlite_file_url_async)
    monkeypatch.setenv("SYNC_SQLALCHEMY_URL", sqlite_file_url_sync)
    monkeypatch.setenv("DUMMY_STORES", "true")
    run_migrations_for_app("storage", db)
    monkeypatch.delenv("ASYNC_SQLALCHEMY_URL")
    monkeypatch.delenv("SYNC_SQLALCHEMY_URL")
    monkeypatch.delenv("DUMMY_STORES")
    yield db
    monkeypatch.delenv("ASYNC_SQLALCHEMY_URL", raising=False)
    monkeypatch.delenv("SYNC_SQLALCHEMY_URL", raising=False)
    monkeypatch.delenv("DUMMY_STORES", raising=False)


@pytest.fixture
def admin_user() -> base_models.APIUser:
    return base_models.APIUser(
        is_admin=True, id="some-random-id-123456", access_token="some-access-token"
    )  # nosec B106


@pytest.fixture
def loggedin_user() -> base_models.APIUser:
    return base_models.APIUser(
        is_admin=False, id="some-random-id-123456", access_token="some-access-token"
    )  # nosec B106


def only(iterable, default=None, too_long=None):
    """From https://github.com/python/importlib_resources/blob/v5.13.0/importlib_resources/_itertools.py#L2."""
    it = iter(iterable)
    first_value = next(it, default)

    try:
        second_value = next(it)
    except StopIteration:
        pass
    else:
        msg = "Expected exactly one item in iterable, but got {!r}, {!r}, " "and perhaps more.".format(
            first_value, second_value
        )
        raise too_long or ValueError(msg)

    return first_value
