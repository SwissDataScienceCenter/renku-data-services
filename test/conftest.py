"""Fixtures for testing."""

import itertools
import operator
from pathlib import Path, PurePosixPath

import pytest
import renku_data_services.resource_pool_models as models
from renku_data_services.resource_pool_adapters import ResourcePoolRepository, UserRepository
from renku_data_services.migrations.core import run_migrations_for_app


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
def patched_importlib_resource_multiplexed_path(monkeypatch):
    """Fix importlib.resources MultiplexedPath iterdir method.

    This was fixed in Python 3.12 to work properly with namespace packages.
    In Python 3.11 it doesn't properly return a correct child path.
    Alembic fails to find migrations if this isn't fixed.
    """
    import importlib.resources.readers

    def _iterdir(self):
        children = (child for path in self._paths for child in path.iterdir())
        by_name = operator.attrgetter("name")
        groups = itertools.groupby(sorted(children, key=by_name), key=by_name)
        return map(self._follow, (locs for name, locs in groups))

    def _follow(cls, children):
        """
        Construct a MultiplexedPath if needed.

        If children contains a sole element, return it.
        Otherwise, return a MultiplexedPath of the items.
        Unless one of the items is not a Directory, then return the first.
        """
        subdirs, one_dir, one_file = itertools.tee(children, 3)

        try:
            return only(one_dir)
        except ValueError:
            try:
                return cls(*subdirs)
            except NotADirectoryError:
                return next(one_file)

    def _joinpath(self, child):
        """
        Return Traversable resolved with any descendants applied.

        Each descendant should be a path segment relative to self
        and each may contain multiple levels separated by
        ``posixpath.sep`` (``/``).
        """
        descendants = [child]
        if not descendants:
            return self
        names = itertools.chain.from_iterable(path.parts for path in map(PurePosixPath, descendants))
        target = next(names)
        matches = (traversable for traversable in self.iterdir() if traversable.name == target)
        try:
            match = next(matches)
        except StopIteration:
            raise Exception("Target not found during traversal.", target, list(names))
        return match.joinpath(*names)

    monkeypatch.setattr(importlib.resources.readers.MultiplexedPath, "iterdir", _iterdir)
    monkeypatch.setattr(importlib.resources.readers.MultiplexedPath, "joinpath", _joinpath)
    monkeypatch.setattr(importlib.resources.readers.MultiplexedPath, "__truediv__", _joinpath)
    setattr(importlib.resources.readers.MultiplexedPath, "_follow", classmethod(_follow))
    yield


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
def admin_user() -> models.APIUser:
    return models.APIUser(is_admin=True, id="some-random-id-123456", access_token="some-access-token")  # nosec B106


@pytest.fixture
def loggedin_user() -> models.APIUser:
    return models.APIUser(is_admin=False, id="some-random-id-123456", access_token="some-access-token")  # nosec B106


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
