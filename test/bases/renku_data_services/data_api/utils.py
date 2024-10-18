import json
from base64 import b64decode
from typing import Any

from dataclasses_avroschema import AvroModel
from sanic import Request
from sanic_testing.testing import SanicASGITestClient, TestingResponse

from renku_data_services.base_models import APIUser
from renku_data_services.message_queue.avro_models.io.renku.events import v2
from renku_data_services.message_queue.models import deserialize_binary
from renku_data_services.message_queue.orm import EventORM


async def create_rp(payload: dict[str, Any], test_client: SanicASGITestClient) -> tuple[Request, TestingResponse]:
    return await test_client.post(
        "/api/data/resource_pools",
        headers={"Authorization": 'Bearer {"is_admin": true}'},
        data=json.dumps(payload),
    )


async def create_user_preferences(
    test_client: SanicASGITestClient, valid_add_pinned_project_payload: dict[str, Any], api_user: APIUser
) -> tuple[Request, TestingResponse]:
    """Create user preferences by adding a pinned project"""
    return await test_client.post(
        "/api/data/user/preferences/pinned_projects",
        headers={"Authorization": f"bearer {api_user.access_token}"},
        data=json.dumps(valid_add_pinned_project_payload),
    )


def merge_headers(*headers: dict[str, str]) -> dict[str, str]:
    """Merge multiple headers."""
    all_headers = dict()
    for h in headers:
        all_headers.update(**h)
    return all_headers


def deserialize_event(event: EventORM) -> AvroModel:
    """Deserialize an EventORM object."""
    event_type_mapping = {
        "group.added": v2.GroupAdded,
        "group.removed": v2.GroupRemoved,
        "group.updated": v2.GroupUpdated,
        "memberGroup.added": v2.GroupMemberAdded,
        "memberGroup.removed": v2.GroupMemberRemoved,
        "memberGroup.updated": v2.GroupMemberUpdated,
        "projectAuth.added": v2.ProjectMemberAdded,
        "projectAuth.removed": v2.ProjectMemberRemoved,
        "projectAuth.updated": v2.ProjectMemberUpdated,
        "project.created": v2.ProjectCreated,
        "project.removed": v2.ProjectRemoved,
        "project.updated": v2.ProjectUpdated,
        "user.added": v2.UserAdded,
        "user.removed": v2.UserRemoved,
        "user.updated": v2.UserUpdated,
        "reprovisioning.started": v2.ReprovisioningStarted,
        "reprovisioning.finished": v2.ReprovisioningFinished,
    }

    event_type = event_type_mapping.get(event.get_message_type())
    if not event_type:
        raise ValueError(f"Unsupported message type: {event.get_message_type()}")

    return deserialize_binary(b64decode(event.payload["payload"]), event_type)


def dataclass_to_str(object) -> str:
    """Convert a dataclass to str to make them hashable."""
    data = object.asdict()
    return json.dumps(data, sort_keys=True, default=str)
