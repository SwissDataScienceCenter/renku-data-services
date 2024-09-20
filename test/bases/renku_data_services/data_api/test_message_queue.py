import asyncio

import pytest

import renku_data_services.message_queue.blueprints
from test.bases.renku_data_services.data_api.utils import dataclass_to_str, deserialize_event


@pytest.mark.asyncio
async def test_search_reprovisioning(
    sanic_client, app_config, create_project, create_group, admin_headers, project_members
) -> None:
    await create_project("Project 1")
    await create_project("Project 2", visibility="public")
    await create_project("Project 3", admin=True)
    await create_project("Project 4", admin=True, visibility="public", members=project_members)

    await create_group("Group 1")
    await create_group("Group 2", admin=True)
    await create_group("Group 3", members=project_members)

    events = await app_config.event_repo._get_pending_events()

    # NOTE: Clear all events before reprovisioning
    await app_config.event_repo.clear()

    _, response = await sanic_client.post("/api/data/search/reprovision", headers=admin_headers)

    assert response.status_code == 201, response.text

    # NOTE: Wait for server to finish the reprovisioning task
    await asyncio.sleep(2)

    reprovisioning_events = await app_config.event_repo._get_pending_events()

    events_before = {dataclass_to_str(deserialize_event(e)) for e in events}
    events_after = {dataclass_to_str(deserialize_event(e)) for e in reprovisioning_events[1:-1]}

    assert events_after == events_before


@pytest.mark.asyncio
async def test_search_only_admins_can_start_reprovisioning(sanic_client, user_headers) -> None:
    _, response = await sanic_client.post("/api/data/search/reprovision", headers=user_headers)

    assert response.status_code == 403, response.text
    assert "You do not have the required permissions for this operation." in response.json["error"]["message"]


async def long_reprovisioning_mock(*_, **__):
    # NOTE: we do not delete the reprovision instance at the end to simulate a long reprovisioning
    print("Running")


@pytest.mark.asyncio
async def test_search_multiple_reprovisioning_not_allowed(sanic_client, admin_headers, monkeypatch) -> None:
    monkeypatch.setattr(renku_data_services.message_queue.blueprints, "reprovision", long_reprovisioning_mock)

    _, response = await sanic_client.post("/api/data/search/reprovision", headers=admin_headers)
    assert response.status_code == 201, response.text

    _, response = await sanic_client.post("/api/data/search/reprovision", headers=admin_headers)

    assert response.status_code == 409, response.text
    assert "A reprovisioning is already in progress" in response.json["error"]["message"]


@pytest.mark.asyncio
async def test_search_get_reprovisioning_status(sanic_client, admin_headers, user_headers, monkeypatch):
    monkeypatch.setattr(renku_data_services.message_queue.blueprints, "reprovision", long_reprovisioning_mock)

    _, response = await sanic_client.get("/api/data/search/reprovision", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json["active"] is False

    # NOTE: Start a reprovisioning
    _, response = await sanic_client.post("/api/data/search/reprovision", headers=admin_headers)
    assert response.status_code == 201, response.text

    _, response = await sanic_client.get("/api/data/search/reprovision", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json["active"] is True


@pytest.mark.asyncio
async def test_search_can_stop_reprovisioning(sanic_client, admin_headers, monkeypatch) -> None:
    monkeypatch.setattr(renku_data_services.message_queue.blueprints, "reprovision", long_reprovisioning_mock)

    _, response = await sanic_client.post("/api/data/search/reprovision", headers=admin_headers)
    assert response.status_code == 201, response.text

    _, response = await sanic_client.delete("/api/data/search/reprovision", headers=admin_headers)
    assert response.status_code == 204, response.text

    _, response = await sanic_client.get("/api/data/search/reprovision", headers=admin_headers)

    assert response.status_code == 200, response.text
    assert response.json["active"] is False
