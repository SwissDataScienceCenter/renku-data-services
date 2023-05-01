"""Fixtures for testing."""

from pathlib import Path

import pytest


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
