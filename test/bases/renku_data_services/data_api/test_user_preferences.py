import json
from test.bases.renku_data_services.data_api.utils import create_user_preferences
from typing import Any, Dict
from uuid import uuid4

import pytest
from sanic import Sanic
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.app_config import Config
from renku_data_services.base_models import APIUser
from renku_data_services.data_api.app import register_all_handlers

_valid_add_pinned_project: Dict[str, Any] = {"project_slug": "user.1/first-project"}


@pytest.fixture
def valid_add_pinned_project_payload() -> Dict[str, Any]:
    return _valid_add_pinned_project


@pytest.fixture
def test_client(app_config: Config) -> SanicASGITestClient:
    app = Sanic(app_config.app_name)
    app = register_all_handlers(app, app_config)
    return SanicASGITestClient(app)


@pytest.fixture
def api_user() -> APIUser:
    id = str(uuid4())
    name = "Some R. User"
    first_name = "Some"
    last_name = "R. User"
    email = "some-user@gmail.com"
    is_admin = False
    return APIUser(
        is_admin=is_admin,
        id=id,
        name=name,
        first_name=first_name,
        last_name=last_name,
        email=email,
        # The dummy authentication client in the tests will parse the access token to create
        # the same APIUser as this when it receives this json-formatted access token
        access_token=json.dumps(
            {
                "id": id,
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "is_admin": is_admin,
                "name": name,
            }
        ),
    )


@pytest.mark.asyncio
async def test_get_user_preferences(
    test_client: SanicASGITestClient, valid_add_pinned_project_payload: Dict[str, Any], api_user: APIUser
):
    _, res = await create_user_preferences(test_client, valid_add_pinned_project_payload, api_user)
    assert res.status_code == 200

    _, res = await test_client.get(
        "/api/data/user/preferences",
        headers={"Authorization": f"bearer {api_user.access_token}"},
    )

    assert res.status_code == 200
    assert res.json is not None
    assert res.json.get("user_id") == api_user.id
    assert res.json.get("pinned_projects") is not None
    assert len(res.json["pinned_projects"].get("project_slugs")) == 1
    project_slugs = res.json["pinned_projects"]["project_slugs"]
    assert project_slugs[0] == "user.1/first-project"


@pytest.mark.asyncio
async def test_post_user_preferences_pinned_projects(
    test_client: SanicASGITestClient, valid_add_pinned_project_payload: Dict[str, Any], api_user: APIUser
):
    _, res = await create_user_preferences(test_client, valid_add_pinned_project_payload, api_user)
    assert res.status_code == 200

    _, res = await test_client.post(
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
    assert project_slugs[0] == "user.1/first-project"
    assert project_slugs[1] == "user.2/second-project"


@pytest.mark.asyncio
async def test_post_user_preferences_pinned_projects_existing(
    test_client: SanicASGITestClient, valid_add_pinned_project_payload: Dict[str, Any], api_user: APIUser
):
    _, res = await create_user_preferences(test_client, valid_add_pinned_project_payload, api_user)
    assert res.status_code == 200

    _, res = await test_client.post(
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
    assert project_slugs[0] == "user.1/first-project"


@pytest.mark.asyncio
async def test_delete_user_preferences_pinned_projects(
    test_client: SanicASGITestClient, valid_add_pinned_project_payload: Dict[str, Any], api_user: APIUser
):
    _, res = await create_user_preferences(test_client, valid_add_pinned_project_payload, api_user)
    assert res.status_code == 200

    _, res = await test_client.delete(
        "/api/data/user/preferences/pinned_projects",
        params=dict(project_slug="user.1/first-project"),
        headers={"Authorization": f"bearer {api_user.access_token}"},
    )

    assert res.status_code == 200
    assert res.json is not None
    assert res.json.get("user_id") == api_user.id
    assert res.json.get("pinned_projects") is not None
    assert len(res.json["pinned_projects"].get("project_slugs")) == 0


@pytest.mark.asyncio
async def test_delete_user_preferences_pinned_projects_unknown(
    test_client: SanicASGITestClient, valid_add_pinned_project_payload: Dict[str, Any], api_user: APIUser
):
    _, res = await create_user_preferences(test_client, valid_add_pinned_project_payload, api_user)
    assert res.status_code == 200

    _, res = await test_client.delete(
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
    assert project_slugs[0] == "user.1/first-project"
