"""Tests for user-scoped session runners."""

from collections.abc import Coroutine
from typing import Any

import pytest
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.crc.models import RemoteConfigurationKind
from renku_data_services.session_runners import models
from renku_data_services.users.models import UserInfo


@pytest.fixture
async def create_resource_pool_for_runners(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], regular_user: UserInfo
) -> Coroutine[Any, Any, dict[str, Any]]:
    async def create_resource_pool_for_runners_helper() -> dict[str, Any]:
        payload = {
            "name": "test_pool",
            "default": False,
            "public": False,
            "classes": [
                {
                    "cpu": 1,
                    "memory": 16,
                    "gpu": 0,
                    "name": "test_pool_class",
                    "max_storage": 32,
                    "default_storage": 1,
                    "default": True,
                }
            ],
            "remote": {
                "kind": RemoteConfigurationKind.runners.value,
            },
        }
        _, res = await sanic_client.post("/api/data/resource_pools", headers=admin_headers, json=payload)
        assert res.status_code == 201, res.text
        assert res.json is not None
        resource_pool = res.json

        payload = [{"member_type": "user", "id": regular_user.id, "role": "viewer"}]
        _, res = await sanic_client.post(
            f"/api/data/resource_pools/{resource_pool['id']}/members", headers=admin_headers, json=payload
        )
        assert res.status_code == 201, res.text

        return resource_pool

    return create_resource_pool_for_runners_helper


@pytest.mark.asyncio
async def test_post_user_session_runner(
    sanic_client: SanicASGITestClient,
    user_headers: dict[str, str],
    regular_user: UserInfo,
    create_resource_pool_for_runners,
) -> None:
    resource_pool: dict[str, Any] = await create_resource_pool_for_runners()
    resource_pool_id: str = resource_pool["id"]

    payload = {"resource_pool_id": resource_pool_id}
    _, res = await sanic_client.post("/api/data/session_runners/user", headers=user_headers, json=payload)

    assert res.status_code == 201, res.text
    assert res.json is not None
    runner = res.json
    assert runner.get("id") is not None
    assert runner.get("user_id") == regular_user.id
    assert runner.get("resource_pool_id") == resource_pool_id
    assert runner.get("status") == models.RunnerStatus.never_contacted.value
    assert runner.get("registration_token") is not None
    assert runner.get("creation_date") is not None


@pytest.mark.asyncio
async def test_post_user_session_runner_unauthenticated(sanic_client: SanicASGITestClient) -> None:
    payload = {"resource_pool_id": 1}
    _, res = await sanic_client.post("/api/data/session_runners/user", json=payload)

    assert res.status_code == 401, res.text
    assert res.json.get("error", {}).get("message") == "You have to be authenticated to perform this operation."


@pytest.mark.asyncio
async def test_post_user_session_runner_no_access(
    sanic_client: SanicASGITestClient,
    member_1_headers: dict[str, str],
    create_resource_pool_for_runners,
) -> None:
    resource_pool: dict[str, Any] = await create_resource_pool_for_runners()
    resource_pool_id: str = resource_pool["id"]

    payload = {"resource_pool_id": resource_pool_id}
    _, res = await sanic_client.post("/api/data/session_runners/user", headers=member_1_headers, json=payload)

    assert res.status_code == 404, res.text
    assert (
        res.json.get("error", {}).get("message") == f"Resource pool with id '{resource_pool_id}' "
        "does not exist or you do not have access to it."
    )


@pytest.mark.asyncio
async def test_post_user_session_runner_incompatible_pool(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    user_headers: dict[str, str],
    regular_user: UserInfo,
    create_resource_pool_for_runners,
) -> None:
    resource_pool: dict[str, Any] = await create_resource_pool_for_runners()
    resource_pool_id: str = resource_pool["id"]

    payload = {"remote": {}}
    _, res = await sanic_client.patch(
        f"/api/data/resource_pools/{resource_pool_id}", headers=admin_headers, json=payload
    )
    assert res.status_code == 200, res.text

    payload = {"resource_pool_id": resource_pool_id}
    _, res = await sanic_client.post("/api/data/session_runners/user", headers=user_headers, json=payload)

    assert res.status_code == 422, res.text
    assert res.json is not None
    assert (
        res.json.get("error", {}).get("message") == f"Resource pool with id '{resource_pool_id}' "
        "does not accept session runners."
    )
