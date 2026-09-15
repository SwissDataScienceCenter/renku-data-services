import uuid

import pytest

from renku_data_services.base_models.core import AuthenticatedAPIUser
from renku_data_services.users.core import validate_unsaved_ssh_key
from renku_data_services.users.db import SSHKeyRepository
from test.utils import KindCluster

# Public throwaway ed25519 key, no personal comment (same vector as test_core.py).
VALID_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPXhsNCQyI4HlAkaUIujCoGv3isiGoDR/MpS2yKlMfPY"
MISSING_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


async def test_identity_resolves_owner(sanic_client, app_manager_instance):
    owner = AuthenticatedAPIUser(id=str(uuid.uuid4()), access_token="token")
    await app_manager_instance.kc_user_repo.get_or_create_user(owner, owner.id)
    repo = SSHKeyRepository(app_manager_instance.config.db.async_session_maker)
    await repo.insert_ssh_key(requested_by=owner, ssh_key=validate_unsaved_ssh_key(VALID_KEY, None))

    _, response = await sanic_client.post(
        "/api/data/internal/ssh_keys/identity",
        json={"public_key": VALID_KEY},
    )
    assert response.status_code == 200, response.text
    assert response.json["user_id"] == owner.id


async def test_identity_unknown_key_is_404(sanic_client, app_manager_instance):
    _, response = await sanic_client.post(
        "/api/data/internal/ssh_keys/identity",
        json={"public_key": VALID_KEY},
    )
    assert response.status_code == 404


async def test_identity_malformed_key_is_404(sanic_client, app_manager_instance):
    _, response = await sanic_client.post(
        "/api/data/internal/ssh_keys/identity",
        json={"public_key": "not a key"},
    )
    assert response.status_code == 404


@pytest.mark.xdist_group("sessions")
async def test_authorize_unknown_session_is_404(sanic_client, app_manager_instance, cluster: KindCluster):
    _, response = await sanic_client.get(
        f"/api/data/internal/sessions/{MISSING_ID}/authorize",
        params={"user_id": "someone"},
    )
    assert response.status_code == 404


async def test_authorize_missing_user_id_is_422(sanic_client, app_manager_instance):
    _, response = await sanic_client.get(
        f"/api/data/internal/sessions/{MISSING_ID}/authorize",
    )
    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")
async def test_authorize_owner_allowed_and_other_user_denied(
    app_manager_instance,
    sanic_client,
    user_headers,
    regular_user,
    create_project,
    create_resource_pool,
    create_session_launcher,
    cluster: KindCluster,
    amalthea_installation,
):
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
        # the owner may open it
        _, response = await sanic_client.get(
            f"/api/data/internal/sessions/{session_id}/authorize",
            params={"user_id": regular_user.id},
        )
        assert response.status_code == 204, response.text

        # a different user is denied on the same existing session
        _, response = await sanic_client.get(
            f"/api/data/internal/sessions/{session_id}/authorize",
            params={"user_id": str(uuid.uuid4())},
        )
        assert response.status_code == 404
    finally:
        await app_manager_instance.config.nb_config.k8s_v2_client.delete_session(session_id, regular_user.id)
