import base64

import pytest
from authzed.api.v1 import Consistency, ReadRelationshipsRequest, RelationshipFilter
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.app_config.config import Config
from renku_data_services.authz.authz import ResourceType
from renku_data_services.authz.models import Role
from renku_data_services.message_queue.avro_models.io.renku.events import v2
from renku_data_services.message_queue.models import deserialize_binary
from renku_data_services.migrations.core import run_migrations_for_app


@pytest.mark.asyncio
async def test_migration_to_f34b87ddd954(
    sanic_client_no_migrations: SanicASGITestClient, app_config: Config, user_headers, admin_headers
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
    # The migrations should create user namespaces in authzed
    _, response = await sanic_client.get("/api/data/users", headers=admin_headers)
    user_ids_db = [i["id"] for i in response.json]
    namespace_user_ids_authzed = []
    async for user_namespace in app_config.authz.client.ReadRelationships(
        ReadRelationshipsRequest(
            consistency=Consistency(fully_consistent=True),
            relationship_filter=RelationshipFilter(
                resource_type=ResourceType.user_namespace.value, optional_relation=Role.OWNER.value
            ),
        )
    ):
        namespace_user_ids_authzed.append(user_namespace.relationship.subject.object.object_id)
    assert set(user_ids_db) == set(namespace_user_ids_authzed)
