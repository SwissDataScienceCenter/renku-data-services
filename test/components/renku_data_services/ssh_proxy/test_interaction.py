"""Tests for the internal SSH session clock endpoints."""

import json
import uuid
from collections.abc import AsyncIterable, AsyncIterator

import pytest_asyncio
from box import Box
from sanic import Sanic

from renku_data_services.authn.dummy import DummyAuthenticator
from renku_data_services.base_api.error_handler import CustomErrorHandler
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER
from renku_data_services.k8s.db import K8sDbCache
from renku_data_services.k8s.models import (
    DeletePropagationPolicy,
    K8sObject,
    K8sObjectFilter,
    K8sObjectMeta,
    K8sPatches,
)
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.notebooks.constants import AMALTHEA_SESSION_GVK
from renku_data_services.ssh_proxy import apispec as ssh_proxy_apispec
from renku_data_services.ssh_proxy.blueprints import SSHSessionInteractionBP
from test.utils import SanicReusableASGITestClient

MISSING_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
SESSION_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAW"
URL = "/api/data/internal/sessions/{session_id}/interaction"


def role_headers() -> dict[str, str]:
    token = json.dumps({"id": "service-account-ssh-proxy", "roles": ["ssh-proxy"], "is_admin": False})
    return {"Authorization": f"Bearer {token}"}


def user_token_headers() -> dict[str, str]:
    token = json.dumps({"id": str(uuid.uuid4()), "is_admin": False})
    return {"Authorization": f"Bearer {token}"}


class FakeK8sClient:
    """K8s client stub: only get and patch matter for the clock route."""

    def __init__(self, live: K8sObject | None) -> None:
        self.live = live
        self.patches: list[K8sPatches] = []

    async def get(self, meta: K8sObjectMeta) -> K8sObject | None:
        return self.live

    async def patch(self, meta: K8sObjectMeta, patch: K8sPatches) -> K8sObject:
        self.patches.append(patch)
        return self.live or meta.with_manifest({})

    async def create(self, obj: K8sObject, refresh: bool) -> K8sObject:
        raise NotImplementedError

    async def delete(
        self,
        meta: K8sObjectMeta,
        propagation_policy: DeletePropagationPolicy = DeletePropagationPolicy.foreground,
    ) -> None:
        raise NotImplementedError

    def list(self, _filter: K8sObjectFilter) -> AsyncIterable[K8sObject]:
        raise NotImplementedError

    async def logs(self, meta: K8sObjectMeta, max_log_lines: int | None = None) -> dict[str, AsyncIterator[str]]:
        raise NotImplementedError


def session_object(owner: str, labels: dict[str, str] | None = None, **status) -> K8sObject:
    return K8sObject(
        name=SESSION_ID,
        namespace="default",
        cluster=DEFAULT_K8S_CLUSTER,
        gvk=AMALTHEA_SESSION_GVK,
        user_id=owner,
        manifest=Box(
            {
                "metadata": {
                    "name": SESSION_ID,
                    "labels": labels if labels is not None else {"renku.io/frontend-variant": "ssh"},
                },
                "spec": {"culling": {"maxIdleDuration": "24h"}},
                "status": status,
            }
        ),
    )


@pytest_asyncio.fixture
async def client_factory(app_manager_instance):
    run_migrations_for_app("common")
    session_maker = app_manager_instance.config.db.async_session_maker
    cache = K8sDbCache(session_maker=session_maker)

    def make(live: K8sObject | None) -> tuple[SanicReusableASGITestClient, FakeK8sClient]:
        k8s = FakeK8sClient(live)
        bp = SSHSessionInteractionBP(
            name="ssh_session_interaction",
            url_prefix="/api/data",
            authenticator=DummyAuthenticator(),
            k8s_db_cache=cache,
            k8s_client=k8s,
        )
        app = Sanic(f"test_ssh_session_interaction_{uuid.uuid4().hex}")
        app.blueprint(bp.blueprint())
        app.error_handler = CustomErrorHandler(ssh_proxy_apispec)
        return SanicReusableASGITestClient(app), k8s

    return make


async def test_clock_requires_a_token(client_factory):
    client, _ = client_factory(None)
    async with client as c:
        _, response = await c.get(URL.format(session_id=MISSING_ID))
    assert response.status_code == 401


async def test_clock_rejects_an_unparseable_token(client_factory):
    client, _ = client_factory(None)
    async with client as c:
        _, response = await c.get(URL.format(session_id=MISSING_ID), headers={"Authorization": "Bearer not-a-token"})
    assert response.status_code == 401


async def test_clock_without_role_is_403(client_factory):
    client, _ = client_factory(None)
    async with client as c:
        _, response = await c.get(URL.format(session_id=MISSING_ID), headers=user_token_headers())
    assert response.status_code == 403


async def test_unknown_session_is_404(client_factory):
    client, k8s = client_factory(None)
    async with client as c:
        _, touch = await c.post(URL.format(session_id=MISSING_ID), headers=role_headers())
        _, clock = await c.get(URL.format(session_id=MISSING_ID), headers=role_headers())
    assert touch.status_code == 404
    assert clock.status_code == 404
    assert k8s.patches == []


async def test_non_ssh_session_is_404(client_factory, app_manager_instance):
    cache = K8sDbCache(session_maker=app_manager_instance.config.db.async_session_maker)
    session = session_object(str(uuid.uuid4()), labels={"renku.io/frontend-variant": "jupyterlab"}, state="Running")
    await cache.upsert(session)
    client, k8s = client_factory(session)
    async with client as c:
        _, touch = await c.post(URL.format(session_id=SESSION_ID), headers=role_headers())
        _, clock = await c.get(URL.format(session_id=SESSION_ID), headers=role_headers())
    assert touch.status_code == 404
    assert clock.status_code == 404
    assert k8s.patches == []
