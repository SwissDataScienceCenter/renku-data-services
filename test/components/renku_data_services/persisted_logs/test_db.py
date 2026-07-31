"""Tests for the persisted logs database."""

import pytest
import pytest_asyncio

from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.persisted_logs import loki_api
from renku_data_services.persisted_logs.collector import LokiLogReader
from renku_data_services.persisted_logs.db import (
    AmaltheaSessionPersistedLogsWriteRepository,
    ImageBuildPersistedLogsWriteRepository,
)


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
):
    # TODO: Setup the database with a session launcher
    # dependency_manager.session_repo.insert_launcher()
    logs_stream = LokiLogReader._process_session_logs(session_logs_response)
    async_session_maker = dependency_manager.config.db.async_session_maker
    async with async_session_maker() as session, session.begin():
        result = await session_logs_repo.insert_session_logs(session=session, logs_stream=logs_stream)
    assert result is None
