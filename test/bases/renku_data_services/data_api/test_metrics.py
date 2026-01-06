import re
from collections.abc import AsyncGenerator
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.base_models.metrics import ProjectCreationType
from renku_data_services.metrics.core import StagingMetricsService


@pytest_asyncio.fixture
async def sanic_metrics_client(monkeypatch, app_manager, sanic_client) -> AsyncGenerator[SanicASGITestClient, None]:
    monkeypatch.setenv("POSTHOG_ENABLED", "true")

    # NOTE: Replace the `project_created` and `session_launcher_created` methods with actual implementations to store
    # metrics in the database.
    metrics = StagingMetricsService(enabled=True, metrics_repo=app_manager.metrics_repo)
    metrics_mock = cast(MagicMock, app_manager.metrics)
    metrics_mock.configure_mock(
        project_created=metrics.project_created, session_launcher_created=metrics.session_launcher_created
    )

    yield sanic_client

    metrics_mock.configure_mock(project_created=AsyncMock(), session_launcher_created=AsyncMock())


@pytest.mark.asyncio
async def test_metrics_are_stored(sanic_metrics_client, app_manager, create_project, create_session_launcher) -> None:
    project = await create_project(name="Project", sanic_client=sanic_metrics_client)
    await create_session_launcher("Launcher 1", project_id=project["id"])

    events = [e async for e in app_manager.metrics_repo.get_unprocessed_metrics()]
    events.sort(key=lambda e: e.timestamp)

    assert len(events) == 2

    project_created = events[0]
    assert re.match(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$", str(project_created.id))
    assert project_created.event == "project_created"
    assert project_created.metadata_ == {"project_creation_kind": ProjectCreationType.new.value}

    session_launcher_created = events[1]
    assert re.match(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$", str(session_launcher_created.id))
    assert session_launcher_created.event == "session_launcher_created"
    assert session_launcher_created.metadata_ == {"environment_image_source": "image", "environment_kind": "CUSTOM"}
