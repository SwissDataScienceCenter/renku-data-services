from test.bases.renku_data_services.data_api.utils import create_user_preferences
from typing import Any, Dict

import pytest
from sanic import Sanic
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.data_api.app import register_all_handlers
from renku_data_services.data_api.config import Config

_valid_add_pinned_project: Dict[str, Any] = {"project_slug": "user.1/first-project"}


@pytest.fixture
def valid_add_pinned_project_payload() -> Dict[str, Any]:
    return _valid_add_pinned_project


@pytest.fixture
def test_client(app_config: Config) -> SanicASGITestClient:
    app = Sanic(app_config.app_name)
    app = register_all_handlers(app, app_config)
    return SanicASGITestClient(app)


@pytest.mark.asyncio
async def test_get_user_preferences(test_client: SanicASGITestClient, valid_add_pinned_project_payload: Dict[str, Any]):
    _, res = await create_user_preferences(test_client, valid_add_pinned_project_payload)
    assert res.status_code == 200

    _, res = await test_client.get(
        "/api/data/user_preferences",
        headers={"Authorization": "bearer test"},
    )

    assert res.status_code == 200
    assert res.json is not None
    assert res.json.get("user_id") == "some-id"
    assert res.json.get("pinned_projects") is not None
    assert len(res.json["pinned_projects"].get("project_slugs")) == 1
    project_slugs = res.json["pinned_projects"]["project_slugs"]
    assert project_slugs[0] == "user.1/first-project"
