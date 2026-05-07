import re
import subprocess
from collections.abc import AsyncGenerator
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.base_models.metrics import ProjectCreationType
from renku_data_services.metrics.core import StagingMetricsService


def _has_docker() -> bool:
    """Check if docker is available."""
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


@pytest_asyncio.fixture
async def sanic_metrics_client(monkeypatch, app_manager, sanic_client) -> AsyncGenerator[SanicASGITestClient, None]:
    monkeypatch.setenv("POSTHOG_ENABLED", "true")

    # NOTE: Replace the metrics methods with actual implementations to store metrics in the database.
    metrics = StagingMetricsService(enabled=True, metrics_repo=app_manager.metrics_repo)
    metrics_mock = cast(MagicMock, app_manager.metrics)
    metrics_mock.configure_mock(
        project_created=metrics.project_created,
        session_launcher_created=metrics.session_launcher_created,
        session_started=metrics.session_started,
        session_resumed=metrics.session_resumed,
        session_stopped=metrics.session_stopped,
        session_hibernated=metrics.session_hibernated,
        user_requested_session_resume=metrics.user_requested_session_resume,
    )

    yield sanic_client

    metrics_mock.configure_mock(
        project_created=AsyncMock(),
        session_launcher_created=AsyncMock(),
        session_started=AsyncMock(),
        session_resumed=AsyncMock(),
        session_stopped=AsyncMock(),
        session_hibernated=AsyncMock(),
        user_requested_session_resume=AsyncMock(),
    )


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


@pytest.mark.asyncio
@pytest.mark.skipif(not _has_docker(), reason="docker is not available - kind cannot create clusters")
async def test_session_metrics_are_stored(
    sanic_metrics_client, app_manager, create_project, create_session_launcher, create_resource_pool, user_headers
) -> None:
    """Test that session lifecycle metrics with metadata are stored correctly.

    Note: This test requires kind cluster to be available.
    """

    project = await create_project(name="Project", sanic_client=sanic_metrics_client)
    # Create a resource pool with a resource class to use in the session launcher
    resource_pool = await create_resource_pool(admin=True)
    resource_class_id = resource_pool["classes"][0]["id"]

    # Create a session launcher with a resource_class_id
    session_launcher = await create_session_launcher(
        "Launcher 1", project_id=project["id"], resource_class_id=resource_class_id
    )

    # Start a session to trigger session_started metric
    _, res = await sanic_metrics_client.post(
        "/api/data/sessions",
        headers=user_headers,
        json={
            "launcher_id": session_launcher["id"],
            "name": "Test Session",
            "resource_class_id": resource_class_id,
        },
    )
    assert res.status_code == 201, f"Expected 201, got {res.status_code}. Response: {res.json}"
    session_data = res.json
    # The session response uses 'name' as the identifier, not 'id'
    session_id = session_data["name"]

    events = [e async for e in app_manager.metrics_repo.get_unprocessed_metrics()]
    events.sort(key=lambda e: e.timestamp)

    # Find session_started event
    session_started_events = [e for e in events if e.event == "session_started"]
    assert len(session_started_events) >= 1
    session_started_event = session_started_events[0]

    # Verify session_started has required metadata fields
    metadata = session_started_event.metadata_
    assert metadata["session_id"] == session_id
    assert "resource_class_id" in metadata
    assert "resource_pool_id" in metadata
    assert "resource_class_name" in metadata
    assert "cpu" in metadata
    assert "memory" in metadata
    assert "gpu" in metadata
    assert "storage" in metadata

    # Simulate session resumed event
    metrics = StagingMetricsService(enabled=True, metrics_repo=app_manager.metrics_repo)
    await metrics.session_resumed(
        user=type("APIUser", (), {"id": user_headers["X-API-Token"]})(),
        metadata={
            "session_id": session_id,
            "resource_class_id": "1",
            "resource_pool_id": "pool-1",
            "resource_class_name": "test-pool.test-class",
            "cpu": 2000,
            "memory": 4096,
            "gpu": 0,
            "storage": 10000,
        },
    )

    # Reload events
    events = [e async for e in app_manager.metrics_repo.get_unprocessed_metrics()]
    events.sort(key=lambda e: e.timestamp)

    # Find session_resumed event
    session_resumed_events = [e for e in events if e.event == "session_resumed"]
    assert len(session_resumed_events) >= 1
    session_resumed_event = session_resumed_events[-1]

    # Verify session_resumed has required metadata fields
    metadata = session_resumed_event.metadata_
    assert metadata["session_id"] == session_id
    assert "resource_class_id" in metadata
    assert "resource_pool_id" in metadata
    assert "resource_class_name" in metadata
    assert "cpu" in metadata
    assert "memory" in metadata
    assert "gpu" in metadata
    assert "storage" in metadata

    # Simulate user_requested_session_resume event
    await metrics.user_requested_session_resume(
        user=type("APIUser", (), {"id": user_headers["X-API-Token"]})(),
        metadata={
            "session_id": session_id,
            "resource_class_id": "1",
            "resource_pool_id": "pool-1",
            "resource_class_name": "test-pool.test-class",
            "cpu": 2000,
            "memory": 4096,
            "gpu": 0,
        },
    )

    # Reload events
    events = [e async for e in app_manager.metrics_repo.get_unprocessed_metrics()]
    events.sort(key=lambda e: e.timestamp)

    # Find user_requested_session_resume event
    resume_request_events = [e for e in events if e.event == "user_requested_session_resume"]
    assert len(resume_request_events) >= 1
    resume_request_event = resume_request_events[-1]

    # Verify user_requested_session_resume has required metadata fields
    metadata = resume_request_event.metadata_
    assert metadata["session_id"] == session_id
    assert "resource_class_id" in metadata
    assert "resource_pool_id" in metadata
    assert "resource_class_name" in metadata
    assert "cpu" in metadata
    assert "memory" in metadata
    assert "gpu" in metadata
    assert "storage" not in metadata  # This event doesn't include storage

    # Also verify session_hibernated metric
    await metrics.session_hibernated(
        user=type("APIUser", (), {"id": user_headers["X-API-Token"]})(),
        metadata={"session_id": session_id},
    )

    events = [e async for e in app_manager.metrics_repo.get_unprocessed_metrics()]
    events.sort(key=lambda e: e.timestamp)

    hibernated_events = [e for e in events if e.event == "session_hibernated"]
    assert len(hibernated_events) >= 1
    hibernated_event = hibernated_events[-1]
    assert hibernated_event.metadata_["session_id"] == session_id


@pytest.mark.asyncio
async def test_session_metrics_metadata_structure(app_manager) -> None:
    """Test that session metrics store metadata with correct structure."""
    # Clear existing metrics before running the test
    await app_manager.metrics_repo.delete_all_metrics()

    metrics = StagingMetricsService(enabled=True, metrics_repo=app_manager.metrics_repo)

    # Create mock user
    mock_user = type("APIUser", (), {"id": "test-user-123", "is_authenticated": True})()

    # Test session_started metadata
    await metrics.session_started(
        user=mock_user,
        metadata={
            "session_id": "session-456",
            "resource_class_id": 5,
            "resource_pool_id": "pool-abc",
            "resource_class_name": "test-pool.test-class",
            "cpu": 2000,
            "memory": 4096,
            "gpu": 1,
            "storage": 10000,
        },
    )

    events = [e async for e in app_manager.metrics_repo.get_unprocessed_metrics()]
    session_started_event = [e for e in events if e.event == "session_started"][0]

    # Verify all metadata fields are preserved
    assert session_started_event.metadata_["session_id"] == "session-456"
    assert session_started_event.metadata_["resource_class_id"] == 5
    assert session_started_event.metadata_["resource_pool_id"] == "pool-abc"
    assert session_started_event.metadata_["resource_class_name"] == "test-pool.test-class"
    assert session_started_event.metadata_["cpu"] == 2000
    assert session_started_event.metadata_["memory"] == 4096
    assert session_started_event.metadata_["gpu"] == 1
    assert session_started_event.metadata_["storage"] == 10000

    # Test session_resumed metadata
    await metrics.session_resumed(
        user=mock_user,
        metadata={
            "session_id": "session-789",
            "resource_class_id": 10,
            "resource_pool_id": "pool-def",
            "resource_class_name": "different-pool.different-class",
            "cpu": 4000,
            "memory": 8192,
            "gpu": 2,
            "storage": 20000,
        },
    )

    events = [e async for e in app_manager.metrics_repo.get_unprocessed_metrics()]
    session_resumed_event = [e for e in events if e.event == "session_resumed"][0]

    assert session_resumed_event.metadata_["session_id"] == "session-789"
    assert session_resumed_event.metadata_["resource_class_id"] == 10
    assert session_resumed_event.metadata_["resource_pool_id"] == "pool-def"
    assert session_resumed_event.metadata_["resource_class_name"] == "different-pool.different-class"
    assert session_resumed_event.metadata_["cpu"] == 4000
    assert session_resumed_event.metadata_["memory"] == 8192
    assert session_resumed_event.metadata_["gpu"] == 2
    assert session_resumed_event.metadata_["storage"] == 20000

    # Test user_requested_session_resume metadata
    await metrics.user_requested_session_resume(
        user=mock_user,
        metadata={
            "session_id": "session-999",
            "resource_class_id": 3,
            "resource_pool_id": "pool-xyz",
            "resource_class_name": "another-pool.another-class",
            "cpu": 1000,
            "memory": 2048,
            "gpu": 0,
        },
    )

    events = [e async for e in app_manager.metrics_repo.get_unprocessed_metrics()]
    resume_event = [e for e in events if e.event == "user_requested_session_resume"][0]

    assert resume_event.metadata_["session_id"] == "session-999"
    assert resume_event.metadata_["resource_class_id"] == 3
    assert resume_event.metadata_["resource_pool_id"] == "pool-xyz"
    assert resume_event.metadata_["resource_class_name"] == "another-pool.another-class"
    assert resume_event.metadata_["cpu"] == 1000
    assert resume_event.metadata_["memory"] == 2048
    assert resume_event.metadata_["gpu"] == 0
    assert "storage" not in resume_event.metadata_

    # Verify the event count
    all_events = [e async for e in app_manager.metrics_repo.get_unprocessed_metrics()]
    assert len(all_events) == 3  # session_started, session_resumed, user_requested_session_resume
