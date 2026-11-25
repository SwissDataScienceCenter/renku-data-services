"""Tests for retrieving persisted logs from the API."""

from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import replace
from typing import Any

import pytest
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.persisted_logs import collector, loki_api, models
from renku_data_services.persisted_logs.db import (
    AmaltheaSessionPersistedLogsWriteRepository,
    ImageBuildPersistedLogsWriteRepository,
)
from renku_data_services.users.models import UserInfo
from test.components.renku_data_services.persisted_logs.conftest import (  # noqa: F401 Used fixture
    build_logs_response,
    session_logs_response,
)


@pytest.fixture
def session_logs_repo() -> AmaltheaSessionPersistedLogsWriteRepository:
    return AmaltheaSessionPersistedLogsWriteRepository()


@pytest.fixture
def build_logs_repo() -> ImageBuildPersistedLogsWriteRepository:
    return ImageBuildPersistedLogsWriteRepository()


@pytest.fixture
def insert_persisted_session_logs(
    app_manager_instance: DependencyManager,
    session_logs_response: loki_api.LokiQueryRangeResponse,  # noqa: F811 Using fixture
    session_logs_repo: AmaltheaSessionPersistedLogsWriteRepository,
) -> Callable[[str, str], Coroutine[Any, Any, None]]:
    async def insert_persisted_session_logs_helper(user_id: str, launcher_id: str) -> None:
        # Replace the log line metadata for the test
        async def _make_logs_stream() -> AsyncIterator[models.UnsavedSessionLogLine]:
            source = collector.LokiLogReader._process_session_logs(session_logs_response)
            async for item in source:
                yield replace(item, user_id=user_id, launcher_id=launcher_id)

        async_session_maker = app_manager_instance.config.db.async_session_maker
        async with async_session_maker() as session, session.begin():
            await session_logs_repo.insert_session_logs(session=session, logs_stream=_make_logs_stream())

    return insert_persisted_session_logs_helper


@pytest.fixture
def insert_persisted_build_logs(
    app_manager_instance: DependencyManager,
    build_logs_response: loki_api.LokiQueryRangeResponse,  # noqa: F811 Using fixture
    build_logs_repo: ImageBuildPersistedLogsWriteRepository,
) -> Callable[[str], Coroutine[Any, Any, None]]:
    async def insert_persisted_build_logs_helper(build_id: str) -> None:
        # Replace the log line metadata for the test
        async def _make_logs_stream() -> AsyncIterator[models.UnsavedSessionLogLine]:
            source = collector.LokiLogReader._process_image_build_logs(build_logs_response)
            async for item in source:
                yield replace(item, build_id=build_id)

        async_session_maker = app_manager_instance.config.db.async_session_maker
        async with async_session_maker() as session, session.begin():
            await build_logs_repo.insert_build_logs(session=session, logs_stream=_make_logs_stream())

    return insert_persisted_build_logs_helper


@pytest.mark.asyncio
async def test_get_persisted_session_logs_empty(
    sanic_client: SanicASGITestClient, user_headers: dict[str, str], create_project, create_session_launcher
) -> None:
    project = await create_project(sanic_client, "My Project")
    session_launcher = await create_session_launcher("My Launcher", project_id=project["id"])
    session_launcher_id = session_launcher["id"]

    _, res = await sanic_client.get(f"/api/data/persisted_logs/sessions/{session_launcher_id}", headers=user_headers)

    assert res.status_code == 404, res.text

    _, res = await sanic_client.get(
        f"/api/data/persisted_logs/sessions/{session_launcher_id}/runs", headers=user_headers
    )

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json == []


@pytest.mark.asyncio
async def test_get_persisted_session_logs_unauthorized(
    sanic_client: SanicASGITestClient, create_project, create_session_launcher
) -> None:
    project = await create_project(sanic_client, "My Project")
    session_launcher = await create_session_launcher("My Launcher", project_id=project["id"])
    session_launcher_id = session_launcher["id"]

    _, res = await sanic_client.get(f"/api/data/persisted_logs/sessions/{session_launcher_id}")

    assert res.status_code == 401, res.text

    _, res = await sanic_client.get(f"/api/data/persisted_logs/sessions/{session_launcher_id}/runs")

    assert res.status_code == 401, res.text


@pytest.mark.asyncio
async def test_get_persisted_session_logs(
    sanic_client: SanicASGITestClient,
    regular_user: UserInfo,
    user_headers: dict[str, str],
    create_project,
    create_session_launcher,
    insert_persisted_session_logs: Callable[[str, str], Coroutine[Any, Any, None]],
) -> None:
    project = await create_project(sanic_client, "My Project")
    session_launcher = await create_session_launcher("My Launcher", project_id=project["id"])
    session_launcher_id = session_launcher["id"]

    await insert_persisted_session_logs(user_id=regular_user.id, launcher_id=session_launcher_id)

    _, res = await sanic_client.get(f"/api/data/persisted_logs/sessions/{session_launcher_id}", headers=user_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    persisted_logs = res.json
    assert persisted_logs.get("run") is not None
    run = persisted_logs["run"]
    assert run.get("launcher_id") == session_launcher_id
    assert persisted_logs.get("logs") is not None
    assert len(persisted_logs["logs"]) == 2
    assert persisted_logs["logs"][0].get("container") == "amalthea-session"
    assert persisted_logs["logs"][0].get("logs") is not None
    main_logs = persisted_logs["logs"][0]["logs"]
    expected_log_line = {"timestamp": "1785482091170410038", "log_line": "7/10\n"}
    assert expected_log_line in main_logs

    _, res = await sanic_client.get(
        f"/api/data/persisted_logs/sessions/{session_launcher_id}/runs", headers=user_headers
    )

    assert res.status_code == 200, res.text
    assert res.json is not None
    session_runs = res.json
    assert len(session_runs) == 1
    session_run = session_runs[0]
    assert session_run.get("launcher_id") == session_launcher_id


@pytest.mark.asyncio
async def test_get_persisted_session_logs_with_different_user(
    sanic_client: SanicASGITestClient,
    regular_user: UserInfo,
    member_1_user: UserInfo,
    member_1_headers: dict[str, str],
    create_project,
    create_session_launcher,
    insert_persisted_session_logs: Callable[[str, str], Coroutine[Any, Any, None]],
) -> None:
    project = await create_project(
        sanic_client,
        "My Project",
        members=[{"id": member_1_user.id, "role": "editor"}],
    )
    session_launcher = await create_session_launcher("My Launcher", project_id=project["id"])
    session_launcher_id = session_launcher["id"]

    await insert_persisted_session_logs(user_id=regular_user.id, launcher_id=session_launcher_id)

    _, res = await sanic_client.get(
        f"/api/data/persisted_logs/sessions/{session_launcher_id}", headers=member_1_headers
    )

    assert res.status_code == 404, res.text
    assert res.json is not None
    assert res.json.get("error", dict()).get("message") is not None
    assert "does not have persisted logs" in res.json["error"]["message"]

    _, res = await sanic_client.get(
        f"/api/data/persisted_logs/sessions/{session_launcher_id}/runs", headers=member_1_headers
    )

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json == []


@pytest.mark.asyncio
async def test_get_persisted_build_logs_empty(
    sanic_client: SanicASGITestClient,
    user_headers: dict[str, str],
    create_project,
    create_session_launcher,
    finish_image_build,
) -> None:
    project = await create_project(sanic_client, "My Project")
    session_launcher = await create_session_launcher(
        "My Launcher",
        project_id=project["id"],
        environment={
            "repository": "https://github.com/some/repo",
            "builder_variant": "python",
            "frontend_variant": "vscodium",
            "environment_image_source": "build",
        },
    )
    environment_id = session_launcher["environment"]["id"]
    _, res = await sanic_client.get(f"/api/data/environments/{environment_id}/builds", headers=user_headers)
    assert res.status_code == 200, res.text
    assert res.json is not None
    build = res.json[0]
    build_id = build["id"]
    await finish_image_build(build_id=build_id)

    _, res = await sanic_client.get(f"/api/data/persisted_logs/builds/{build_id}", headers=user_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    build_logs = res.json
    assert build_logs.get("logs") == []


@pytest.mark.asyncio
async def test_get_persisted_build_logs_unauthorized(
    sanic_client: SanicASGITestClient,
    user_headers: dict[str, str],
    create_project,
    create_session_launcher,
    finish_image_build,
) -> None:
    project = await create_project(sanic_client, "My Project")
    session_launcher = await create_session_launcher(
        "My Launcher",
        project_id=project["id"],
        environment={
            "repository": "https://github.com/some/repo",
            "builder_variant": "python",
            "frontend_variant": "vscodium",
            "environment_image_source": "build",
        },
    )
    environment_id = session_launcher["environment"]["id"]
    _, res = await sanic_client.get(f"/api/data/environments/{environment_id}/builds", headers=user_headers)
    assert res.status_code == 200, res.text
    assert res.json is not None
    build = res.json[0]
    build_id = build["id"]
    await finish_image_build(build_id=build_id)

    _, res = await sanic_client.get(f"/api/data/persisted_logs/builds/{build_id}")

    assert res.status_code == 401, res.text


@pytest.mark.asyncio
async def test_get_persisted_build_logs(
    sanic_client: SanicASGITestClient,
    user_headers: dict[str, str],
    create_project,
    create_session_launcher,
    finish_image_build,
    insert_persisted_build_logs: Callable[[str], Coroutine[Any, Any, None]],
) -> None:
    project = await create_project(sanic_client, "My Project")
    session_launcher = await create_session_launcher(
        "My Launcher",
        project_id=project["id"],
        environment={
            "repository": "https://github.com/some/repo",
            "builder_variant": "python",
            "frontend_variant": "vscodium",
            "environment_image_source": "build",
        },
    )
    environment_id = session_launcher["environment"]["id"]
    _, res = await sanic_client.get(f"/api/data/environments/{environment_id}/builds", headers=user_headers)
    assert res.status_code == 200, res.text
    assert res.json is not None
    build = res.json[0]
    build_id = build["id"]
    await finish_image_build(build_id=build_id)

    await insert_persisted_build_logs(build_id=build_id)

    _, res = await sanic_client.get(f"/api/data/persisted_logs/builds/{build_id}", headers=user_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    build_logs = res.json
    assert build_logs.get("logs") is not None
    assert len(build_logs["logs"]) == 1
    assert build_logs["logs"][0].get("container") == "step-build-and-push"
    assert build_logs["logs"][0].get("logs") is not None
    main_logs = build_logs["logs"][0]["logs"]
    expected_log_line = {
        "timestamp": "1785482342006624181",
        "log_line": "Saving harbor.dev.renku.ch/renku-build/renku-build:renku-01kyvgffxtxv4qk0dyjkx0zsa5...\n",
    }
    assert expected_log_line in main_logs


@pytest.mark.asyncio
async def test_get_persisted_build_logs_with_different_users(
    sanic_client: SanicASGITestClient,
    user_headers: dict[str, str],
    member_1_user: UserInfo,
    member_1_headers: dict[str, str],
    member_2_user: UserInfo,
    member_2_headers: dict[str, str],
    create_project,
    create_session_launcher,
    finish_image_build,
    insert_persisted_build_logs: Callable[[str], Coroutine[Any, Any, None]],
) -> None:
    project = await create_project(
        sanic_client,
        "My Project",
        members=[{"id": member_1_user.id, "role": "editor"}, {"id": member_2_user.id, "role": "viewer"}],
    )
    session_launcher = await create_session_launcher(
        "My Launcher",
        project_id=project["id"],
        environment={
            "repository": "https://github.com/some/repo",
            "builder_variant": "python",
            "frontend_variant": "vscodium",
            "environment_image_source": "build",
        },
    )
    environment_id = session_launcher["environment"]["id"]
    _, res = await sanic_client.get(f"/api/data/environments/{environment_id}/builds", headers=user_headers)
    assert res.status_code == 200, res.text
    assert res.json is not None
    build = res.json[0]
    build_id = build["id"]
    await finish_image_build(build_id=build_id)

    await insert_persisted_build_logs(build_id=build_id)

    # Member 1 should have access to logs (project editor)
    _, res = await sanic_client.get(f"/api/data/persisted_logs/builds/{build_id}", headers=member_1_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    build_logs = res.json
    assert build_logs.get("logs") is not None
    assert len(build_logs["logs"]) == 1
    assert build_logs["logs"][0].get("container") == "step-build-and-push"
    assert build_logs["logs"][0].get("logs") is not None
    main_logs = build_logs["logs"][0]["logs"]
    expected_log_line = {
        "timestamp": "1785482342006624181",
        "log_line": "Saving harbor.dev.renku.ch/renku-build/renku-build:renku-01kyvgffxtxv4qk0dyjkx0zsa5...\n",
    }
    assert expected_log_line in main_logs

    # Member 2 should not have access to logs (project viewer)
    _, res = await sanic_client.get(f"/api/data/persisted_logs/builds/{build_id}", headers=member_2_headers)

    assert res.status_code == 404, res.text
