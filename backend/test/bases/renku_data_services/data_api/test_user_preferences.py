import json
from typing import Any
from uuid import uuid4

import pytest
from sanic_testing.testing import SanicASGITestClient
from syrupy.filters import props

from renku_data_services.base_models import APIUser
from test.bases.renku_data_services.data_api.utils import (
    create_user_preferences,
    create_user_preferences_dismiss_banner,
)

_valid_add_pinned_project: list[dict[str, Any]] = [
    {"project_slug": "user.1/first-project"},
    {"project_slug": "john-doe-1/my-project-1"},
    {"project_slug": "a-1-2-3/b-1-2-3"},
]


@pytest.fixture
def api_user() -> APIUser:
    id = str(uuid4())
    full_name = "Some R. User"
    first_name = "Some"
    last_name = "R. User"
    email = "some-user@gmail.com"
    is_admin = False
    return APIUser(
        is_admin=is_admin,
        id=id,
        full_name=full_name,
        # The dummy authentication client in the tests will parse the access token to create
        # the same APIUser as this when it receives this json-formatted access token
        access_token=json.dumps(
            {
                "id": id,
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "is_admin": is_admin,
                "full_name": full_name,
            }
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("valid_add_pinned_project_payload", _valid_add_pinned_project)
async def test_get_user_preferences(
    sanic_client: SanicASGITestClient, valid_add_pinned_project_payload: dict[str, Any], api_user: APIUser, snapshot
) -> None:
    _, res = await create_user_preferences(sanic_client, valid_add_pinned_project_payload, api_user)
    assert res.status_code == 200

    _, res = await sanic_client.get(
        "/api/data/user/preferences",
        headers={"Authorization": f"bearer {api_user.access_token}"},
    )

    assert res.status_code == 200
    assert res.json is not None
    assert res.json.get("user_id") == api_user.id
    assert res.json.get("pinned_projects") is not None
    assert len(res.json["pinned_projects"].get("project_slugs")) == 1
    project_slugs = res.json["pinned_projects"]["project_slugs"]
    assert project_slugs[0] == valid_add_pinned_project_payload["project_slug"]
    assert res.json == snapshot(exclude=props("user_id"))


@pytest.mark.asyncio
@pytest.mark.parametrize("valid_add_pinned_project_payload", _valid_add_pinned_project)
async def test_post_user_preferences_pinned_projects(
    sanic_client: SanicASGITestClient, valid_add_pinned_project_payload: dict[str, Any], api_user: APIUser
) -> None:
    _, res = await create_user_preferences(sanic_client, valid_add_pinned_project_payload, api_user)
    assert res.status_code == 200

    _, res = await sanic_client.post(
        "/api/data/user/preferences/pinned_projects",
        headers={"Authorization": f"bearer {api_user.access_token}"},
        data=json.dumps(dict(project_slug="/user.2/second-project///")),
    )
    assert res.status_code == 422
    _, res = await sanic_client.post(
        "/api/data/user/preferences/pinned_projects",
        headers={"Authorization": f"bearer {api_user.access_token}"},
        data=json.dumps(dict(project_slug="user.2/second-project")),
    )

    assert res.status_code == 200
    assert res.json is not None
    assert res.json.get("user_id") == api_user.id
    assert res.json.get("pinned_projects") is not None
    assert len(res.json["pinned_projects"].get("project_slugs")) == 2
    project_slugs = res.json["pinned_projects"]["project_slugs"]
    assert project_slugs[0] == valid_add_pinned_project_payload["project_slug"]
    assert project_slugs[1] == "user.2/second-project"


@pytest.mark.asyncio
@pytest.mark.parametrize("valid_add_pinned_project_payload", _valid_add_pinned_project)
async def test_post_user_preferences_pinned_projects_existing(
    sanic_client: SanicASGITestClient, valid_add_pinned_project_payload: dict[str, Any], api_user: APIUser
) -> None:
    _, res = await create_user_preferences(sanic_client, valid_add_pinned_project_payload, api_user)
    assert res.status_code == 200

    _, res = await sanic_client.post(
        "/api/data/user/preferences/pinned_projects",
        headers={"Authorization": f"bearer {api_user.access_token}"},
        data=json.dumps(valid_add_pinned_project_payload),
    )

    assert res.status_code == 200
    assert res.json is not None
    assert res.json.get("user_id") == api_user.id
    assert res.json.get("pinned_projects") is not None
    assert len(res.json["pinned_projects"].get("project_slugs")) == 1
    project_slugs = res.json["pinned_projects"]["project_slugs"]
    assert project_slugs[0] == valid_add_pinned_project_payload["project_slug"]


@pytest.mark.asyncio
@pytest.mark.parametrize("valid_add_pinned_project_payload", _valid_add_pinned_project)
async def test_delete_user_preferences_pinned_projects(
    sanic_client: SanicASGITestClient, valid_add_pinned_project_payload: dict[str, Any], api_user: APIUser
) -> None:
    _, res = await create_user_preferences(sanic_client, valid_add_pinned_project_payload, api_user)
    assert res.status_code == 200

    _, res = await sanic_client.delete(
        "/api/data/user/preferences/pinned_projects",
        params=dict(project_slug=valid_add_pinned_project_payload["project_slug"]),
        headers={"Authorization": f"bearer {api_user.access_token}"},
    )

    assert res.status_code == 200
    assert res.json is not None
    assert res.json.get("user_id") == api_user.id
    assert res.json.get("pinned_projects") is not None
    assert len(res.json["pinned_projects"].get("project_slugs")) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("valid_add_pinned_project_payload", _valid_add_pinned_project)
async def test_delete_user_preferences_pinned_projects_unknown(
    sanic_client: SanicASGITestClient, valid_add_pinned_project_payload: dict[str, Any], api_user: APIUser
) -> None:
    _, res = await create_user_preferences(sanic_client, valid_add_pinned_project_payload, api_user)
    assert res.status_code == 200

    _, res = await sanic_client.delete(
        "/api/data/user/preferences/pinned_projects",
        params=dict(project_slug="user.2/second-project"),
        headers={"Authorization": f"bearer {api_user.access_token}"},
    )

    assert res.status_code == 200
    assert res.json is not None
    assert res.json.get("user_id") == api_user.id
    assert res.json.get("pinned_projects") is not None
    assert len(res.json["pinned_projects"].get("project_slugs")) == 1
    project_slugs = res.json["pinned_projects"]["project_slugs"]
    assert project_slugs[0] == valid_add_pinned_project_payload["project_slug"]


@pytest.mark.asyncio
async def test_add_user_preferences_dismiss_projects_migration_banner(
    sanic_client: SanicASGITestClient, api_user: APIUser
) -> None:
    _, res = await create_user_preferences_dismiss_banner(sanic_client, api_user)
    assert res.status_code == 200

    assert res.json is not None
    assert res.json.get("user_id") == api_user.id
    assert res.json.get("pinned_projects") == {"project_slugs": []}
    assert not res.json.get("show_project_migration_banner")
    assert res.json.get("show_project_migration_banner") is not None

    _, res = await sanic_client.delete(
        "/api/data/user/preferences/dismiss_project_migration_banner",
        headers={"Authorization": f"bearer {api_user.access_token}"},
    )

    assert res.status_code == 200
    assert res.json.get("show_project_migration_banner")
    assert res.json.get("show_project_migration_banner") is not None
