import uuid

import pytest_asyncio
from box import Box
from sanic import Sanic

from renku_data_services.base_api.error_handler import CustomErrorHandler
from renku_data_services.base_models.core import AuthenticatedAPIUser
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER
from renku_data_services.k8s.db import K8sDbCache
from renku_data_services.k8s.models import K8sObject
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.notebooks.constants import AMALTHEA_SESSION_GVK
from renku_data_services.ssh_proxy import apispec as ssh_proxy_apispec
from renku_data_services.ssh_proxy.blueprints import SSHProxyBP
from renku_data_services.users.core import validate_unsaved_ssh_key
from renku_data_services.users.db import SSHKeyRepository
from test.utils import SanicReusableASGITestClient

# Public throwaway ed25519 key, no personal comment (same vector as test_core.py).
VALID_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPXhsNCQyI4HlAkaUIujCoGv3isiGoDR/MpS2yKlMfPY"
OTHER_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDifferentKeyAAAAAAAAAAAAAAAAAAAAAAAAAAA"
MISSING_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
SESSION_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAW"
URL = "/api/secrets/internal/sessions/{session_id}/authorize"


@pytest_asyncio.fixture
async def ssh_proxy_client(app_manager_instance) -> SanicReusableASGITestClient:
    run_migrations_for_app("common")
    session_maker = app_manager_instance.config.db.async_session_maker
    bp = SSHProxyBP(
        name="ssh_proxy",
        url_prefix="/api/secrets",
        ssh_key_repo=SSHKeyRepository(session_maker=session_maker),
        k8s_db_cache=K8sDbCache(session_maker=session_maker),
    )
    app = Sanic("test_ssh_proxy")
    app.blueprint(bp.blueprint())
    app.error_handler = CustomErrorHandler(ssh_proxy_apispec)
    async with SanicReusableASGITestClient(app) as client:
        yield client


async def test_authorize_unknown_key_is_404(ssh_proxy_client):
    _, response = await ssh_proxy_client.post(URL.format(session_id=MISSING_ID), json={"public_key": VALID_KEY})
    assert response.status_code == 404


async def test_authorize_malformed_key_is_404(ssh_proxy_client):
    _, response = await ssh_proxy_client.post(URL.format(session_id=MISSING_ID), json={"public_key": "not a key"})
    assert response.status_code == 404


async def test_authorize_missing_public_key_is_422(ssh_proxy_client):
    _, response = await ssh_proxy_client.post(URL.format(session_id=MISSING_ID), json={})
    assert response.status_code == 422


async def test_authorize_missing_body_is_422(ssh_proxy_client):
    _, response = await ssh_proxy_client.post(URL.format(session_id=MISSING_ID))
    assert response.status_code == 422


async def test_authorize_owner_allowed_and_other_key_denied(ssh_proxy_client, app_manager_instance):
    owner = AuthenticatedAPIUser(id=str(uuid.uuid4()), access_token="token")
    await app_manager_instance.kc_user_repo.get_or_create_user(owner, owner.id)
    repo = SSHKeyRepository(app_manager_instance.config.db.async_session_maker)
    await repo.insert_ssh_key(requested_by=owner, ssh_key=validate_unsaved_ssh_key(VALID_KEY, None))
    cache = K8sDbCache(session_maker=app_manager_instance.config.db.async_session_maker)
    await cache.upsert(
        K8sObject(
            name=SESSION_ID,
            namespace="default",
            cluster=DEFAULT_K8S_CLUSTER,
            gvk=AMALTHEA_SESSION_GVK,
            manifest=Box({"metadata": {"name": SESSION_ID}}),
            user_id=owner.id,
        )
    )

    # the key's owner may open it
    _, response = await ssh_proxy_client.post(URL.format(session_id=SESSION_ID), json={"public_key": VALID_KEY})
    assert response.status_code == 204, response.text

    # an unregistered key is denied on the same existing session
    _, response = await ssh_proxy_client.post(URL.format(session_id=SESSION_ID), json={"public_key": OTHER_KEY})
    assert response.status_code == 404
