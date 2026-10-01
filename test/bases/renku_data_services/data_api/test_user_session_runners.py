"""Tests for user-scoped session runners."""

from collections.abc import Callable, Coroutine
from typing import Any

import pytest
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.crc.models import RemoteConfigurationKind
from renku_data_services.session_runners import models
from renku_data_services.users.models import UserInfo


@pytest.fixture
async def create_resource_pool_for_runners(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], regular_user: UserInfo
) -> Callable[[], Coroutine[Any, Any, dict[str, Any]]]:
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
                "kind": RemoteConfigurationKind.user_runners.value,
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


@pytest.fixture
async def create_user_session_runner(
    sanic_client: SanicASGITestClient, user_headers: dict[str, str], create_resource_pool_for_runners
) -> Callable[[], Coroutine[Any, Any, dict[str, Any]]]:
    async def create_user_session_runner_helper() -> dict[str, Any]:
        resource_pool: dict[str, Any] = await create_resource_pool_for_runners()
        resource_pool_id: str = resource_pool["id"]

        payload = {"resource_pool_id": resource_pool_id}
        _, res = await sanic_client.post("/api/data/session_runners/user", headers=user_headers, json=payload)

        assert res.status_code == 201, res.text

        return res.json

    return create_user_session_runner_helper


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


@pytest.mark.asyncio
async def test_get_all_user_session_runners(
    sanic_client: SanicASGITestClient,
    user_headers: dict[str, str],
    create_resource_pool_for_runners,
) -> None:
    # Check that the initial list of runners is empty
    _, res = await sanic_client.get("/api/data/session_runners/user", headers=user_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json == []

    resource_pool: dict[str, Any] = await create_resource_pool_for_runners()
    resource_pool_id: str = resource_pool["id"]
    payload = {"resource_pool_id": resource_pool_id}
    _, res = await sanic_client.post("/api/data/session_runners/user", headers=user_headers, json=payload)
    assert res.status_code == 201, res.text
    runner = res.json
    assert runner.get("id") is not None
    runner_id = runner["id"]

    _, res = await sanic_client.get("/api/data/session_runners/user", headers=user_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    runners = res.json
    assert len(runners) == 1
    assert runners[0].get("id") == runner_id


@pytest.mark.asyncio
async def test_get_all_user_session_runners_for_all_users_as_admin(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    create_user_session_runner,
) -> None:
    runner: dict[str, Any] = await create_user_session_runner()
    runner_id = runner["id"]

    params = {"all_users": True}
    _, res = await sanic_client.get("/api/data/session_runners/user", params=params, headers=admin_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    runners = res.json
    assert len(runners) == 1
    assert runners[0].get("id") == runner_id


@pytest.mark.asyncio
async def test_get_all_user_session_runners_for_all_users_no_access(
    sanic_client: SanicASGITestClient,
    member_1_headers: dict[str, str],
    create_user_session_runner,
) -> None:
    await create_user_session_runner()

    params = {"all_users": True}
    _, res = await sanic_client.get("/api/data/session_runners/user", params=params, headers=member_1_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json == []


@pytest.mark.asyncio
async def test_get_user_session_runner(
    sanic_client: SanicASGITestClient,
    user_headers: dict[str, str],
    create_resource_pool_for_runners,
) -> None:
    resource_pool: dict[str, Any] = await create_resource_pool_for_runners()
    resource_pool_id: str = resource_pool["id"]
    payload = {"resource_pool_id": resource_pool_id}
    _, res = await sanic_client.post("/api/data/session_runners/user", headers=user_headers, json=payload)
    assert res.status_code == 201, res.text
    runner = res.json
    assert runner.get("id") is not None
    runner_id = runner["id"]

    _, res = await sanic_client.get(f"/api/data/session_runners/user/{runner_id}", headers=user_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json.get("id") == runner_id


@pytest.mark.asyncio
async def test_get_user_session_runner_unauthenticated(
    sanic_client: SanicASGITestClient,
    user_headers: dict[str, str],
    create_resource_pool_for_runners,
) -> None:
    resource_pool: dict[str, Any] = await create_resource_pool_for_runners()
    resource_pool_id: str = resource_pool["id"]
    payload = {"resource_pool_id": resource_pool_id}
    _, res = await sanic_client.post("/api/data/session_runners/user", headers=user_headers, json=payload)
    assert res.status_code == 201, res.text
    runner = res.json
    assert runner.get("id") is not None
    runner_id = runner["id"]

    _, res = await sanic_client.get(f"/api/data/session_runners/user/{runner_id}")

    assert res.status_code == 401, res.text
    assert res.json.get("error", {}).get("message") == "You have to be authenticated to perform this operation."


@pytest.mark.asyncio
async def test_get_user_session_runner_no_access(
    sanic_client: SanicASGITestClient,
    user_headers: dict[str, str],
    member_1_headers: dict[str, str],
    create_resource_pool_for_runners,
) -> None:
    resource_pool: dict[str, Any] = await create_resource_pool_for_runners()
    resource_pool_id: str = resource_pool["id"]
    payload = {"resource_pool_id": resource_pool_id}
    _, res = await sanic_client.post("/api/data/session_runners/user", headers=user_headers, json=payload)
    assert res.status_code == 201, res.text
    runner = res.json
    assert runner.get("id") is not None
    runner_id = runner["id"]

    _, res = await sanic_client.get(
        f"/api/data/session_runners/user/{runner_id}",
        headers=member_1_headers,
    )

    assert res.status_code == 404, res.text
    assert (
        res.json.get("error", {}).get("message") == f"Session runner with id '{runner_id}' "
        "does not exist or you do not have access to it."
    )


@pytest.mark.asyncio
async def test_post_register_user_session_runner(
    sanic_client: SanicASGITestClient,
    create_user_session_runner,
) -> None:
    runner: dict[str, Any] = await create_user_session_runner()
    runner_id = runner["id"]
    registration_token = runner["registration_token"]

    payload = {"registration_token": registration_token}
    _, res = await sanic_client.post("/api/data/session_runners/user/register", json=payload)

    assert res.status_code == 200, res.text
    assert res.json is not None
    result = res.json
    assert result.get("runner") is not None
    assert result["runner"].get("id") == runner["id"]
    assert result.get("auth") is not None
    auth = result["auth"]
    expected_keys = {
        "access_token",
        "token_type",
        "expires_in",
        "refresh_token",
        "refresh_expires_in",
        "scope",
    }
    assert set(auth.keys()) == expected_keys
    assert isinstance(auth.get("access_token"), str)
    assert auth["access_token"] != ""
    assert auth.get("token_type") == "Bearer"
    assert isinstance(auth.get("expires_in"), int)
    assert auth["expires_in"] == 900  # 900 seconds = 15 minutes
    assert isinstance(auth.get("refresh_token"), str)
    assert auth["refresh_token"] != ""
    assert isinstance(auth.get("refresh_expires_in"), int)
    assert auth["refresh_expires_in"] == 3600  # 3600 seconds = 1 hour
    assert auth.get("scope") == f"user_runner:{runner_id}"


@pytest.mark.asyncio
async def test_register_user_session_runner_and_update_status(
    sanic_client: SanicASGITestClient,
    create_user_session_runner,
) -> None:
    runner: dict[str, Any] = await create_user_session_runner()
    runner_id = runner["id"]
    registration_token = runner["registration_token"]
    payload = {"registration_token": registration_token}
    _, res = await sanic_client.post("/api/data/session_runners/user/register", json=payload)
    assert res.status_code == 200, res.text
    auth = res.json["auth"]
    access_token = auth["access_token"]
    runner_headers = {"Authorization": f"Bearer {access_token}"}

    payload = {"status": "not_ready"}
    _, res = await sanic_client.patch(
        f"/api/data/session_runners/user/{runner_id}", headers=runner_headers, json=payload
    )

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json.get("id") == runner_id
    assert res.json.get("status") == "not_ready"

    payload = {"status": "ready"}
    _, res = await sanic_client.patch(
        f"/api/data/session_runners/user/{runner_id}", headers=runner_headers, json=payload
    )

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json.get("id") == runner_id
    assert res.json.get("status") == "ready"

    payload = {"status": "initializing"}
    _, res = await sanic_client.patch(
        f"/api/data/session_runners/user/{runner_id}", headers=runner_headers, json=payload
    )

    assert res.status_code == 422, res.text

    # Check that the registration token is invalid now
    payload = {"registration_token": registration_token}
    _, res = await sanic_client.post("/api/data/session_runners/user/register", json=payload)

    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_delete_user_session_runner(
    sanic_client: SanicASGITestClient,
    user_headers: dict[str, str],
    create_resource_pool_for_runners,
) -> None:
    resource_pool: dict[str, Any] = await create_resource_pool_for_runners()
    resource_pool_id: str = resource_pool["id"]
    payload = {"resource_pool_id": resource_pool_id}
    _, res = await sanic_client.post("/api/data/session_runners/user", headers=user_headers, json=payload)
    assert res.status_code == 201, res.text
    runner = res.json
    assert runner.get("id") is not None
    runner_id = runner["id"]

    _, res = await sanic_client.delete(f"/api/data/session_runners/user/{runner_id}", headers=user_headers)

    assert res.status_code == 204, res.text

    # Check that the runner list is now empty
    _, res = await sanic_client.get("/api/data/session_runners/user", headers=user_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json == []


@pytest.mark.asyncio
async def test_delete_user_session_runner_no_access(
    sanic_client: SanicASGITestClient,
    user_headers: dict[str, str],
    member_1_headers: dict[str, str],
    create_resource_pool_for_runners,
) -> None:
    resource_pool: dict[str, Any] = await create_resource_pool_for_runners()
    resource_pool_id: str = resource_pool["id"]
    payload = {"resource_pool_id": resource_pool_id}
    _, res = await sanic_client.post("/api/data/session_runners/user", headers=user_headers, json=payload)
    assert res.status_code == 201, res.text
    runner = res.json
    assert runner.get("id") is not None
    runner_id = runner["id"]

    _, res = await sanic_client.delete(f"/api/data/session_runners/user/{runner_id}", headers=member_1_headers)

    assert res.status_code == 204, res.text

    # Check that the runner still exists
    _, res = await sanic_client.get(f"/api/data/session_runners/user/{runner_id}", headers=user_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json.get("id") == runner_id
