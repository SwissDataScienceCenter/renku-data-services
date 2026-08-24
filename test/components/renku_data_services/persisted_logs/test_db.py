"""Tests for the persisted logs database."""

from collections.abc import AsyncIterator
from dataclasses import replace

import pytest
import pytest_asyncio
from sqlalchemy import select
from ulid import ULID

from renku_data_services import base_models
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.persisted_logs import loki_api, models
from renku_data_services.persisted_logs import orm as schemas
from renku_data_services.persisted_logs.collector import LokiLogReader
from renku_data_services.persisted_logs.db import (
    AmaltheaSessionPersistedLogsWriteRepository,
    ImageBuildPersistedLogsWriteRepository,
)
from renku_data_services.project.models import Project, UnsavedProject, Visibility
from renku_data_services.session.models import (
    Build,
    LauncherType,
    Platform,
    SessionLauncher,
    UnsavedBuildParameters,
    UnsavedSessionLauncher,
)
from renku_data_services.users.models import UserInfo


@pytest_asyncio.fixture
async def dependency_manager(app_manager_instance: DependencyManager) -> DependencyManager:
    run_migrations_for_app("common")
    return app_manager_instance


@pytest.fixture
def session_logs_repo() -> AmaltheaSessionPersistedLogsWriteRepository:
    return AmaltheaSessionPersistedLogsWriteRepository()


@pytest.fixture
def build_logs_repo() -> ImageBuildPersistedLogsWriteRepository:
    return ImageBuildPersistedLogsWriteRepository()


@pytest_asyncio.fixture
async def regular_user(dependency_manager: DependencyManager) -> base_models.AuthenticatedAPIUser:
    api_user = base_models.AuthenticatedAPIUser(
        id="jane_doe", email="jane.doe@example.org", access_token="my_access_token"
    )
    user_info = await dependency_manager.kc_user_repo.get_or_create_user(requested_by=api_user, id=api_user.id)
    assert user_info is not None
    return api_user


@pytest_asyncio.fixture
async def regular_user_info(
    dependency_manager: DependencyManager, regular_user: base_models.AuthenticatedAPIUser
) -> UserInfo:
    user_info = await dependency_manager.kc_user_repo.get_user(id=regular_user.id)
    assert user_info is not None
    return user_info


@pytest_asyncio.fixture
async def my_project(
    dependency_manager: DependencyManager,
    regular_user: base_models.AuthenticatedAPIUser,
    regular_user_info: UserInfo,
) -> Project:
    project = await dependency_manager.project_repo.insert_project(
        user=regular_user,
        project=UnsavedProject(
            name="My Project",
            slug="my-project",
            visibility=Visibility.PRIVATE,
            created_by=regular_user.id,
            namespace=regular_user_info.namespace.path.serialize(),
        ),
    )
    assert project is not None
    return project


@pytest_asyncio.fixture
async def my_session_launcher(
    dependency_manager: DependencyManager,
    regular_user: base_models.AuthenticatedAPIUser,
    my_project: Project,
) -> SessionLauncher:
    build_parameters = UnsavedBuildParameters(
        repository="https://example.org/repo.git",
        platforms=[Platform.linux_amd64],
        builder_variant="python",
        frontend_variant="vscodium",
    )
    launcher = await dependency_manager.session_repo.insert_launcher(
        user=regular_user,
        launcher=UnsavedSessionLauncher(
            project_id=my_project.id,
            name="My Session",
            description=None,
            resource_class_id=None,
            disk_storage=None,
            env_variables=None,
            environment=build_parameters,
            launcher_type=LauncherType.interactive,
        ),
    )
    assert launcher is not None
    return launcher


@pytest_asyncio.fixture
async def my_build(
    dependency_manager: DependencyManager,
    regular_user: base_models.AuthenticatedAPIUser,
    my_session_launcher: SessionLauncher,
) -> Build:
    builds = await dependency_manager.session_repo.get_environment_builds(
        user=regular_user, environment_id=my_session_launcher.environment.id
    )
    assert builds is not None
    assert len(builds) == 1
    return builds[0]


@pytest.mark.asyncio
async def test_session_latest_log_timestamp_is_none_at_startup(
    session_logs_repo: AmaltheaSessionPersistedLogsWriteRepository, dependency_manager: DependencyManager
):
    async_session_maker = dependency_manager.config.db.async_session_maker
    async with async_session_maker() as session, session.begin():
        ts = await session_logs_repo.get_latest_log_timestamp(session=session)
    assert ts is None


@pytest.mark.asyncio
async def test_insert_session_logs(
    session_logs_response: loki_api.LokiQueryRangeResponse,
    session_logs_repo: AmaltheaSessionPersistedLogsWriteRepository,
    dependency_manager: DependencyManager,
    regular_user: base_models.AuthenticatedAPIUser,
    my_session_launcher: SessionLauncher,
):
    # Replace the log line metadata for the test
    async def _make_logs_stream() -> AsyncIterator[models.UnsavedSessionLogLine]:
        source = LokiLogReader._process_session_logs(session_logs_response)
        async for item in source:
            yield replace(item, user_id=regular_user.id, launcher_id=my_session_launcher.id)

    async_session_maker = dependency_manager.config.db.async_session_maker
    async with async_session_maker() as session, session.begin():
        result = await session_logs_repo.insert_session_logs(session=session, logs_stream=_make_logs_stream())

    expected = models.LogStreamMetadata(log_count=22, last_timestamp=1785482091170416212)
    assert result == expected

    # Check the result of get_latest_log_timestamp()
    async with async_session_maker() as session, session.begin():
        ts = await session_logs_repo.get_latest_log_timestamp(session=session)
    assert ts == expected.last_timestamp


@pytest.mark.asyncio
async def test_insert_session_logs_with_db_failures(
    session_logs_response: loki_api.LokiQueryRangeResponse,
    session_logs_repo: AmaltheaSessionPersistedLogsWriteRepository,
    dependency_manager: DependencyManager,
    regular_user: base_models.AuthenticatedAPIUser,
    my_session_launcher: SessionLauncher,
):
    # Replace the log line metadata for the test
    async def _make_logs_stream() -> AsyncIterator[models.UnsavedSessionLogLine]:
        source = LokiLogReader._process_session_logs(session_logs_response)
        alt_run_id = ULID()
        idx = 0
        async for item in source:
            # # Use correct foreign keys only on half of the log lines
            if idx % 2 == 0:
                yield replace(item, user_id=regular_user.id, run_id=alt_run_id, launcher_id=my_session_launcher.id)
            else:
                yield item
            idx += 1

    async_session_maker = dependency_manager.config.db.async_session_maker
    async with async_session_maker() as session, session.begin():
        result = await session_logs_repo.insert_session_logs(session=session, logs_stream=_make_logs_stream())

    expected = models.LogStreamMetadata(log_count=22, last_timestamp=1785482091170416212)
    assert result == expected

    async with async_session_maker() as session, session.begin():
        stmt = select(schemas.AmaltheaSessionLogORM)
        res = await session.scalars(stmt)
        session_logs_orm = res.all()

    assert len(session_logs_orm) == 11

    # Check the result of get_latest_log_timestamp()
    async with async_session_maker() as session, session.begin():
        ts = await session_logs_repo.get_latest_log_timestamp(session=session)
    assert ts == expected.last_timestamp


@pytest.mark.asyncio
async def test_build_latest_log_timestamp_is_none_at_startup(
    build_logs_repo: ImageBuildPersistedLogsWriteRepository, dependency_manager: DependencyManager
):
    async_session_maker = dependency_manager.config.db.async_session_maker
    async with async_session_maker() as session, session.begin():
        ts = await build_logs_repo.get_latest_log_timestamp(session=session)
    assert ts is None


@pytest.mark.asyncio
async def test_insert_build_logs(
    build_logs_response: loki_api.LokiQueryRangeResponse,
    build_logs_repo: ImageBuildPersistedLogsWriteRepository,
    dependency_manager: DependencyManager,
    my_build: Build,
):
    # Replace the log line metadata for the test
    async def _make_logs_stream() -> AsyncIterator[models.UnsavedBuildLogLine]:
        source = LokiLogReader._process_image_build_logs(build_logs_response)
        async for item in source:
            yield replace(item, build_id=my_build.id)

    async_session_maker = dependency_manager.config.db.async_session_maker
    async with async_session_maker() as session, session.begin():
        result = await build_logs_repo.insert_build_logs(session=session, logs_stream=_make_logs_stream())

    expected = models.LogStreamMetadata(log_count=3, last_timestamp=1785482346922298906)
    assert result == expected

    # Check the result of get_latest_log_timestamp()
    async with async_session_maker() as session, session.begin():
        ts = await build_logs_repo.get_latest_log_timestamp(session=session)
    assert ts == expected.last_timestamp


@pytest.mark.asyncio
async def test_insert_build_logs_with_db_failures(
    build_logs_response: loki_api.LokiQueryRangeResponse,
    build_logs_repo: ImageBuildPersistedLogsWriteRepository,
    dependency_manager: DependencyManager,
    my_build: Build,
):
    # Replace the log line metadata for the test
    async def _make_logs_stream() -> AsyncIterator[models.UnsavedBuildLogLine]:
        source = LokiLogReader._process_image_build_logs(build_logs_response)
        idx = 0
        async for item in source:
            # Use correct foreign keys only on half of the log lines
            if idx % 2 == 0:
                yield replace(item, build_id=my_build.id)
            else:
                yield item
            idx += 1

    async_session_maker = dependency_manager.config.db.async_session_maker
    async with async_session_maker() as session, session.begin():
        result = await build_logs_repo.insert_build_logs(session=session, logs_stream=_make_logs_stream())

    expected = models.LogStreamMetadata(log_count=3, last_timestamp=1785482346922298906)
    assert result == expected

    async with async_session_maker() as session, session.begin():
        stmt = select(schemas.ImageBuildLogORM)
        res = await session.scalars(stmt)
        build_logs_orm = res.all()

    assert len(build_logs_orm) == 2

    # Check the result of get_latest_log_timestamp()
    async with async_session_maker() as session, session.begin():
        ts = await build_logs_repo.get_latest_log_timestamp(session=session)
    assert ts == expected.last_timestamp
