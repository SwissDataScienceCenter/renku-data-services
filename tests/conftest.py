"""Fixtures for testing."""

from pathlib import Path

import pytest

import models
from db.adapter import ResourcePoolRepository, UserRepository


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
    db.do_migrations()
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
    db.do_migrations()
    monkeypatch.delenv("ASYNC_SQLALCHEMY_URL")
    monkeypatch.delenv("SYNC_SQLALCHEMY_URL")
    monkeypatch.delenv("DUMMY_STORES")
    yield db
    monkeypatch.delenv("ASYNC_SQLALCHEMY_URL", raising=False)
    monkeypatch.delenv("SYNC_SQLALCHEMY_URL", raising=False)
    monkeypatch.delenv("DUMMY_STORES", raising=False)


@pytest.fixture
def admin_user() -> models.APIUser:
    return models.APIUser(is_admin=True, id="some-random-id-123456", access_token="some-access-token")  # nosec B106


@pytest.fixture
def loggedin_user() -> models.APIUser:
    return models.APIUser(is_admin=False, id="some-random-id-123456", access_token="some-access-token")  # nosec B106
