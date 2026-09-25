import json

import pytest

from renku_data_services.base_models.core import AuthenticatedAPIUser
from renku_data_services.users.core import validate_unsaved_ssh_key
from renku_data_services.users.db import SSHKeyRepository
from test.utils import KindCluster

# Public throwaway ed25519 key, no personal comment (same vector as test_core.py).
VALID_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPXhsNCQyI4HlAkaUIujCoGv3isiGoDR/MpS2yKlMfPY"
MISSING_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


@pytest.fixture
def ssh_proxy_headers() -> dict[str, str]:
    """A Keycloak service-account token carrying the ssh-proxy realm role."""
    token = json.dumps({"is_admin": False, "id": "service-account-ssh-proxy", "roles": ["ssh-proxy"]})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def wrong_role_headers() -> dict[str, str]:
    """A Keycloak token whose realm roles do not include ssh-proxy."""
    token = json.dumps({"is_admin": False, "id": "some-user", "roles": ["some-other-role"]})
    return {"Authorization": f"Bearer {token}"}


async def test_authorize_no_token_is_401(sanic_client, app_manager_instance):
    _, response = await sanic_client.post(
        f"/api/data/internal/sessions/{MISSING_ID}/authorize",
        json={"public_key": VALID_KEY},
    )
    assert response.status_code == 401


async def test_authorize_user_token_is_403(sanic_client, app_manager_instance, user_headers):
    _, response = await sanic_client.post(
        f"/api/data/internal/sessions/{MISSING_ID}/authorize",
        headers=user_headers,
        json={"public_key": VALID_KEY},
    )
    assert response.status_code == 403


async def test_authorize_admin_bypasses_role(sanic_client, app_manager_instance, admin_headers):
    _, response = await sanic_client.post(
        f"/api/data/internal/sessions/{MISSING_ID}/authorize",
        headers=admin_headers,
        json={"public_key": VALID_KEY},
    )
    assert response.status_code == 404


async def test_authorize_wrong_role_is_403(sanic_client, app_manager_instance, wrong_role_headers):
    _, response = await sanic_client.post(
        f"/api/data/internal/sessions/{MISSING_ID}/authorize",
        headers=wrong_role_headers,
        json={"public_key": VALID_KEY},
    )
    assert response.status_code == 403


async def test_authorize_unknown_key_is_404(sanic_client, app_manager_instance, ssh_proxy_headers):
    _, response = await sanic_client.post(
        f"/api/data/internal/sessions/{MISSING_ID}/authorize",
        headers=ssh_proxy_headers,
        json={"public_key": VALID_KEY},
    )
    assert response.status_code == 404


async def test_authorize_malformed_key_is_404(sanic_client, app_manager_instance, ssh_proxy_headers):
    _, response = await sanic_client.post(
        f"/api/data/internal/sessions/{MISSING_ID}/authorize",
        headers=ssh_proxy_headers,
        json={"public_key": "not a key"},
    )
    assert response.status_code == 404


async def test_authorize_missing_public_key_is_422(sanic_client, app_manager_instance, ssh_proxy_headers):
    _, response = await sanic_client.post(
        f"/api/data/internal/sessions/{MISSING_ID}/authorize",
        headers=ssh_proxy_headers,
        json={},
    )
    assert response.status_code == 422


async def test_authorize_missing_body_is_422(sanic_client, app_manager_instance, ssh_proxy_headers):
    _, response = await sanic_client.post(
        f"/api/data/internal/sessions/{MISSING_ID}/authorize",
        headers=ssh_proxy_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")
async def test_authorize_owner_allowed_and_other_key_denied(
    app_manager_instance,
    sanic_client,
    user_headers,
    ssh_proxy_headers,
    regular_user,
    create_project,
    create_resource_pool,
    create_session_launcher,
    cluster: KindCluster,
    amalthea_installation,
):
    owner = AuthenticatedAPIUser(id=regular_user.id, access_token="token")
    await app_manager_instance.kc_user_repo.get_or_create_user(owner, owner.id)
    repo = SSHKeyRepository(app_manager_instance.config.db.async_session_maker)
    await repo.insert_ssh_key(requested_by=owner, ssh_key=validate_unsaved_ssh_key(VALID_KEY, None))

    project = await create_project(sanic_client, "SSH proxy project", visibility="public")
    resource_pool = await create_resource_pool(admin=True)
    launcher = await create_session_launcher(
        "SSH proxy launcher",
        project_id=project["id"],
        resource_class_id=resource_pool["classes"][0]["id"],
        disk_storage=1,
    )
    _, launched = await sanic_client.post(
        "/api/data/sessions",
        headers=user_headers,
        json={"project_id": project["id"], "launcher_id": launcher["id"]},
    )
    assert launched.status_code == 201, launched.text
    session_id = launched.json["name"]
    try:
        # the key's owner may open it
        _, response = await sanic_client.post(
            f"/api/data/internal/sessions/{session_id}/authorize",
            headers=ssh_proxy_headers,
            json={"public_key": VALID_KEY},
        )
        assert response.status_code == 204, response.text

        # an unregistered key is denied on the same existing session
        _, response = await sanic_client.post(
            f"/api/data/internal/sessions/{session_id}/authorize",
            headers=ssh_proxy_headers,
            json={"public_key": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDifferentKeyAAAAAAAAAAAAAAAAAAAAAAAAAAA"},
        )
        assert response.status_code == 404
    finally:
        await app_manager_instance.config.nb_config.k8s_v2_client.delete_session(session_id, regular_user.id)
