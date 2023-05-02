"""Fixtures for testing."""

from pathlib import Path

import pytest

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
    db.do_migrations()
    monkeypatch.delenv("ASYNC_SQLALCHEMY_URL")
    monkeypatch.delenv("SYNC_SQLALCHEMY_URL")
    yield db
    monkeypatch.delenv("ASYNC_SQLALCHEMY_URL", raising=False)
    monkeypatch.delenv("SYNC_SQLALCHEMY_URL", raising=False)


@pytest.fixture
def pool_repo(sqlite_file_url_sync, sqlite_file_url_async, monkeypatch):
    db = ResourcePoolRepository(sqlite_file_url_sync, sqlite_file_url_async)
    monkeypatch.setenv("ASYNC_SQLALCHEMY_URL", sqlite_file_url_async)
    monkeypatch.setenv("SYNC_SQLALCHEMY_URL", sqlite_file_url_sync)
    db.do_migrations()
    monkeypatch.delenv("ASYNC_SQLALCHEMY_URL")
    monkeypatch.delenv("SYNC_SQLALCHEMY_URL")
    yield db
    monkeypatch.delenv("ASYNC_SQLALCHEMY_URL", raising=False)
    monkeypatch.delenv("SYNC_SQLALCHEMY_URL", raising=False)
