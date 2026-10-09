"""Tests for user-scoped session runners."""

from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

import pytest
from sanic_testing.testing import SanicASGITestClient
from ulid import ULID

from renku_data_services import base_models
from renku_data_services.crc.models import RemoteConfigurationKind
from renku_data_services.session_runners import apispec, models
from renku_data_services.session_runners.db import UserSessionRunnersSchedulingRepository
from renku_data_services.users.models import UserInfo

if TYPE_CHECKING:
    from renku_data_services.data_api.dependencies import DependencyManager


@pytest.fixture
async def create_resource_pool_for_runners(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], regular_user: UserInfo
) -> Callable[[], Coroutine[Any, Any, dict[str, Any]]]:
    """Fixture to create a resource pool which supports user-scoped session runners."""

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
    """Fixture to create a user-scoped session runner."""

    async def create_user_session_runner_helper(resource_pool_id: int | None = None) -> dict[str, Any]:
        if resource_pool_id is None:
            resource_pool: dict[str, Any] = await create_resource_pool_for_runners()
            resource_pool_id: int = resource_pool["id"]

        payload = {"resource_pool_id": resource_pool_id}
        _, res = await sanic_client.post("/api/data/session_runners/user", headers=user_headers, json=payload)

        assert res.status_code == 201, res.text

        return res.json

    return create_user_session_runner_helper


@pytest.fixture
async def create_remote_session(app_manager_instance: "DependencyManager", regular_user_api_user: base_models.APIUser):
    """Fixture to create a (fake) remote Renku session."""

    async def create_remote_session_helper(
        resource_pool_id: int, runner_id: str, user: base_models.APIUser | None = None
    ) -> dict[str, Any]:
        scheduling_repo = UserSessionRunnersSchedulingRepository()
        session_maker = app_manager_instance.config.db.async_session_maker

        user = user or regular_user_api_user
        session_id = f"remote-session-{str(ULID()).lower()}"

        async with session_maker() as session, session.begin():
            runner_id_ulid: ULID = ULID.from_str(runner_id)
            # 1. Make sure the runner is ready
            await app_manager_instance.user_session_runners_repo.update_runner(
                session=session,
                user=user,
                runner_id=runner_id_ulid,
                patch=models.UserSessionRunnerPatch(status=models.RunnerStatus.ready),
            )
            # 2. Create the (fake) remote Renku session
            renku_session = await app_manager_instance.user_session_runners_repo.insert_remote_session(
                user=user,
                renku_session=models.UnsavedRemoteUserSession(session_id=session_id, resource_pool_id=resource_pool_id),
                session=session,
            )
            # 3. Schedule the session onto the runner
            renku_session = await scheduling_repo.update_remote_session_set_runner(
                session=session, renku_session_id=renku_session.session_id, runner_id=runner_id_ulid
            )

        return apispec.RemoteUserSession.model_validate(renku_session).model_dump(exclude_none=True, mode="json")

    return create_remote_session_helper


@pytest.mark.asyncio
async def test_post_user_session_runner(
    sanic_client: SanicASGITestClient,
    user_headers: dict[str, str],
    regular_user: UserInfo,
    create_resource_pool_for_runners,
) -> None:
    resource_pool: dict[str, Any] = await create_resource_pool_for_runners()
    resource_pool_id: int = resource_pool["id"]

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
    resource_pool_id: int = resource_pool["id"]

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
    resource_pool_id: int = resource_pool["id"]

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
    resource_pool_id: int = resource_pool["id"]
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
    resource_pool_id: int = resource_pool["id"]
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
    resource_pool_id: int = resource_pool["id"]
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
    resource_pool_id: int = resource_pool["id"]
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
    resource_pool_id: int = resource_pool["id"]
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
    resource_pool_id: int = resource_pool["id"]
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


@pytest.mark.asyncio
async def test_get_sessions_from_user_runner(
    sanic_client: SanicASGITestClient,
    create_user_session_runner,
    create_remote_session,
) -> None:
    runner: dict[str, Any] = await create_user_session_runner()
    runner_id: str = runner["id"]
    resource_pool_id: int = runner["resource_pool_id"]
    runner_headers = await _register_runner(sanic_client, runner["registration_token"])

    renku_session_1 = await create_remote_session(resource_pool_id=resource_pool_id, runner_id=runner_id)
    renku_session_2 = await create_remote_session(resource_pool_id=resource_pool_id, runner_id=runner_id)

    _, res = await sanic_client.get("/api/data/session_runners/user/sessions", headers=runner_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert len(res.json) == 2
    assert set(item["session_id"] for item in res.json) == {
        renku_session_1["session_id"],
        renku_session_2["session_id"],
    }


@pytest.mark.asyncio
async def test_get_sessions_from_user_runner_only_assigned_sessions(
    sanic_client: SanicASGITestClient,
    create_user_session_runner,
    create_remote_session,
) -> None:
    runner: dict[str, Any] = await create_user_session_runner()
    resource_pool_id: int = runner["resource_pool_id"]
    runner_headers = await _register_runner(sanic_client, runner["registration_token"])
    other_runner: dict[str, Any] = await create_user_session_runner(resource_pool_id=resource_pool_id)

    visible_renku_session = await create_remote_session(resource_pool_id=resource_pool_id, runner_id=runner["id"])
    _not_accessible_renku_session = await create_remote_session(
        resource_pool_id=resource_pool_id, runner_id=other_runner["id"]
    )

    _, res = await sanic_client.get("/api/data/session_runners/user/sessions", headers=runner_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert len(res.json) == 1
    assert res.json[0].get("session_id") == visible_renku_session["session_id"]


@pytest.mark.asyncio
async def test_get_session_from_user_runner(
    sanic_client: SanicASGITestClient,
    create_user_session_runner,
    create_remote_session,
) -> None:
    runner: dict[str, Any] = await create_user_session_runner()
    runner_id: str = runner["id"]
    resource_pool_id: int = runner["resource_pool_id"]
    runner_headers = await _register_runner(sanic_client, runner["registration_token"])

    renku_session = await create_remote_session(resource_pool_id=resource_pool_id, runner_id=runner_id)
    session_id = renku_session["session_id"]

    _, res = await sanic_client.get(f"/api/data/session_runners/user/sessions/{session_id}", headers=runner_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json == renku_session


@pytest.mark.asyncio
async def test_get_session_from_user_runner_no_access(
    sanic_client: SanicASGITestClient,
    create_user_session_runner,
    create_remote_session,
) -> None:
    runner: dict[str, Any] = await create_user_session_runner()
    resource_pool_id: int = runner["resource_pool_id"]
    runner_headers = await _register_runner(sanic_client, runner["registration_token"])
    other_runner: dict[str, Any] = await create_user_session_runner(resource_pool_id=resource_pool_id)

    renku_session = await create_remote_session(resource_pool_id=resource_pool_id, runner_id=other_runner["id"])
    session_id = renku_session["session_id"]

    _, res = await sanic_client.get(f"/api/data/session_runners/user/sessions/{session_id}", headers=runner_headers)

    assert res.status_code == 404, res.text
    assert (
        res.json.get("error", {}).get("message") == f"The session {session_id} "
        "does not exist or you do not have access to it."
    )


@pytest.mark.asyncio
async def test_get_session_secrets_from_user_runner(
    sanic_client: SanicASGITestClient,
    create_user_session_runner,
    create_remote_session,
) -> None:
    runner: dict[str, Any] = await create_user_session_runner()
    runner_id: str = runner["id"]
    resource_pool_id: int = runner["resource_pool_id"]
    runner_headers = await _register_runner(sanic_client, runner["registration_token"])

    renku_session = await create_remote_session(resource_pool_id=resource_pool_id, runner_id=runner_id)
    session_id = renku_session["session_id"]

    _, res = await sanic_client.get(
        f"/api/data/session_runners/user/sessions/{session_id}/secrets", headers=runner_headers
    )

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json == []


@pytest.mark.asyncio
async def test_patch_session_secrets_from_user_runner(
    sanic_client: SanicASGITestClient,
    create_user_session_runner,
    create_remote_session,
) -> None:
    runner: dict[str, Any] = await create_user_session_runner()
    runner_id: str = runner["id"]
    resource_pool_id: int = runner["resource_pool_id"]
    runner_headers = await _register_runner(sanic_client, runner["registration_token"])

    renku_session = await create_remote_session(resource_pool_id=resource_pool_id, runner_id=runner_id)
    session_id = renku_session["session_id"]

    payload = [{"name": "my_secret", "value": "hello"}]
    _, res = await sanic_client.patch(
        f"/api/data/session_runners/user/sessions/{session_id}/secrets",
        headers=runner_headers,
        json=payload,
    )

    assert res.status_code == 200, res.text

    _, res = await sanic_client.get(
        f"/api/data/session_runners/user/sessions/{session_id}/secrets", headers=runner_headers
    )

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert len(res.json) == 1
    secret = res.json[0]
    assert secret == {"name": "my_secret", "value": "hello"}


async def _register_runner(sanic_client: SanicASGITestClient, registration_token: str) -> dict[str, str]:
    """Register a runner and return the runner's authorization header."""
    payload = {"registration_token": registration_token}
    _, res = await sanic_client.post("/api/data/session_runners/user/register", json=payload)
    assert res.status_code == 200, res.text
    auth = res.json["auth"]
    access_token = auth["access_token"]
    return {"Authorization": f"Bearer {access_token}"}
