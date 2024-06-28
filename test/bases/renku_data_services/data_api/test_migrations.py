import base64
from typing import Any

import pytest
from alembic.script import ScriptDirectory
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.app_config.config import Config
from renku_data_services.message_queue.avro_models.io.renku.events import v2
from renku_data_services.message_queue.models import deserialize_binary
from renku_data_services.migrations.core import downgrade_migrations_for_app, get_alembic_config, run_migrations_for_app
from renku_data_services.users.models import UserInfo


@pytest.mark.asyncio
async def test_unique_migration_head() -> None:
    cfg = get_alembic_config(name="common")
    script = ScriptDirectory.from_config(cfg)

    heads = script.get_revisions(script.get_heads())
    heads = [h.revision for h in heads]

    assert len(heads) == 1


@pytest.mark.asyncio
async def test_upgrade_downgrade_cycle(
    app_config: Config, sanic_client_no_migrations: SanicASGITestClient, admin_headers: dict, admin_user: UserInfo
) -> None:
    # Migrate to head and create a project
    run_migrations_for_app("common", "head")
    await app_config.kc_user_repo.initialize(app_config.kc_api)
    await app_config.group_repo.generate_user_namespaces()
    payload: dict[str, Any] = {
        "name": "test_project",
        "namespace": f"{admin_user.first_name}.{admin_user.last_name}",
    }
    _, res = await sanic_client_no_migrations.post("/api/data/projects", headers=admin_headers, json=payload)
    assert res.status_code == 201
    # Migrate/downgrade a few times but end on head
    downgrade_migrations_for_app("common", "base")
    run_migrations_for_app("common", "head")
    downgrade_migrations_for_app("common", "base")
    run_migrations_for_app("common", "head")
    # Try to make the same project again
    # NOTE: The engine has to be disposed otherwise it caches the postgres types (i.e. enums)
    # from previous migrations and then trying to create a project below fails with the message
    # cache postgres lookup failed for type XXXX.
    await app_config.db._async_engine.dispose()
    await app_config.kc_user_repo.initialize(app_config.kc_api)
    await app_config.group_repo.generate_user_namespaces()
    _, res = await sanic_client_no_migrations.post("/api/data/projects", headers=admin_headers, json=payload)
    assert res.status_code == 201, res.json


# !IMPORTANT: This test can only be run on v2 of the authz schema
@pytest.mark.skip
@pytest.mark.asyncio
async def test_migration_to_f34b87ddd954(
    sanic_client_no_migrations: SanicASGITestClient, app_config: Config, user_headers: dict, admin_headers: dict
) -> None:
    run_migrations_for_app("common", "d8676f0cde53")
    await app_config.kc_user_repo.initialize(app_config.kc_api)
    await app_config.group_repo.generate_user_namespaces()
    sanic_client = sanic_client_no_migrations
    payloads = [
        {
            "name": "Group1",
            "slug": "group-1",
            "description": "Group 1 Description",
        },
        {
            "name": "Group2",
            "slug": "group-2",
            "description": "Group 2 Description",
        },
    ]
    added_group_ids = []
    for payload in payloads:
        _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
        assert response.status_code == 201
        added_group_ids.append(response.json["id"])
    run_migrations_for_app("common", "f34b87ddd954")
    # The migration should delete all groups
    _, response = await sanic_client.get("/api/data/groups", headers=user_headers)
    assert response.status_code == 200
    assert len(response.json) == 0
    # The database should have delete events for the groups
    events_orm = await app_config.event_repo._get_pending_events()
    group_removed_events = [
        deserialize_binary(base64.b64decode(e.payload["payload"]), v2.GroupRemoved)
        for e in events_orm
        if e.queue == "group.removed"
    ]
    assert len(group_removed_events) == 2
    assert set(added_group_ids) == {e.id for e in group_removed_events}
