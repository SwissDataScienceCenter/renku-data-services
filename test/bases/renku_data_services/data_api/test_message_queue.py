import pytest

from test.bases.renku_data_services.data_api.utils import dataclass_to_str, deserialize_event


@pytest.mark.asyncio
async def test_reprovisioning(
    sanic_client, app_config, create_project, create_group, admin_headers, user_headers, project_members
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

    reprovisioning_events = await app_config.event_repo._get_pending_events()

    events_before = {dataclass_to_str(deserialize_event(e)) for e in events}
    events_after = {dataclass_to_str(deserialize_event(e)) for e in reprovisioning_events[1:-1]}

    assert events_after == events_before
