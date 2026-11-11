"""Tests for the internal SSH session clock endpoints."""

import json
import uuid
from collections.abc import AsyncIterable, AsyncIterator
from datetime import UTC, datetime, timedelta

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


async def test_touch_writes_one_field_and_answers_204(client_factory, app_manager_instance):
    cache = K8sDbCache(session_maker=app_manager_instance.config.db.async_session_maker)
    session = session_object(str(uuid.uuid4()), state="Running")
    await cache.upsert(session)
    client, k8s = client_factory(session)
    before = datetime.now(UTC)
    async with client as c:
        _, response = await c.post(URL.format(session_id=SESSION_ID), headers=role_headers())
    after = datetime.now(UTC)

    assert response.status_code == 204
    assert response.body == b""
    assert len(k8s.patches) == 1
    patch = k8s.patches[0]
    assert list(patch.keys()) == ["spec"]
    assert list(patch["spec"].keys()) == ["culling"]
    last_interaction = patch["spec"]["culling"]["lastInteraction"]
    assert last_interaction.endswith("Z")
    written = datetime.fromisoformat(last_interaction.replace("Z", "+00:00"))
    assert before.replace(microsecond=0) <= written <= after


async def test_touch_does_not_patch_when_the_session_is_unknown(client_factory):
    client, k8s = client_factory(None)
    async with client as c:
        _, response = await c.post(URL.format(session_id=MISSING_ID), headers=role_headers())
    assert response.status_code == 404
    assert k8s.patches == []


async def test_clock_returns_remaining_seconds_and_alive(client_factory, app_manager_instance):
    cache = K8sDbCache(session_maker=app_manager_instance.config.db.async_session_maker)
    deadline = datetime.now(UTC) + timedelta(minutes=10)
    session = session_object(str(uuid.uuid4()), state="Running", willHibernateAt=deadline.isoformat())
    await cache.upsert(session)
    client, _ = client_factory(session)
    async with client as c:
        _, response = await c.get(URL.format(session_id=SESSION_ID), headers=role_headers())
    assert response.status_code == 200
    body = response.json
    assert 590 <= body["seconds_until_hibernate"] <= 600
    assert body["alive"] is True


async def test_clock_without_a_deadline_returns_null(client_factory, app_manager_instance):
    cache = K8sDbCache(session_maker=app_manager_instance.config.db.async_session_maker)
    session = session_object(str(uuid.uuid4()), state="Running")
    await cache.upsert(session)
    client, _ = client_factory(session)
    async with client as c:
        _, response = await c.get(URL.format(session_id=SESSION_ID), headers=role_headers())
    assert response.json["seconds_until_hibernate"] is None
    assert response.json["alive"] is True


async def test_clock_reports_the_idle_age(client_factory, app_manager_instance):
    cache = K8sDbCache(session_maker=app_manager_instance.config.db.async_session_maker)
    session = session_object(str(uuid.uuid4()), state="Running")
    session.manifest["spec"]["culling"]["lastInteraction"] = (datetime.now(UTC) - timedelta(seconds=120)).isoformat()
    await cache.upsert(session)
    client, _ = client_factory(session)
    async with client as c:
        _, response = await c.get(URL.format(session_id=SESSION_ID), headers=role_headers())
    assert 115 <= response.json["seconds_since_last_interaction"] <= 125


async def test_clock_without_a_touch_reports_a_null_idle_age(client_factory, app_manager_instance):
    cache = K8sDbCache(session_maker=app_manager_instance.config.db.async_session_maker)
    session = session_object(str(uuid.uuid4()), state="Running")
    await cache.upsert(session)
    client, _ = client_factory(session)
    async with client as c:
        _, response = await c.get(URL.format(session_id=SESSION_ID), headers=role_headers())
    assert response.json["seconds_since_last_interaction"] is None


async def test_clock_hibernated_is_not_alive(client_factory, app_manager_instance):
    cache = K8sDbCache(session_maker=app_manager_instance.config.db.async_session_maker)
    session = session_object(str(uuid.uuid4()), state="Hibernated")
    await cache.upsert(session)
    client, _ = client_factory(session)
    async with client as c:
        _, response = await c.get(URL.format(session_id=SESSION_ID), headers=role_headers())
    assert response.json["alive"] is False


async def test_clock_running_degraded_is_alive(client_factory, app_manager_instance):
    cache = K8sDbCache(session_maker=app_manager_instance.config.db.async_session_maker)
    session = session_object(str(uuid.uuid4()), state="RunningDegraded")
    await cache.upsert(session)
    client, _ = client_factory(session)
    async with client as c:
        _, response = await c.get(URL.format(session_id=SESSION_ID), headers=role_headers())
    assert response.json["alive"] is True


async def test_clock_returns_404_when_the_session_is_gone(client_factory, app_manager_instance):
    cache = K8sDbCache(session_maker=app_manager_instance.config.db.async_session_maker)
    await cache.upsert(session_object(str(uuid.uuid4()), state="Running"))
    client, _ = client_factory(None)
    async with client as c:
        _, response = await c.get(URL.format(session_id=SESSION_ID), headers=role_headers())
    assert response.status_code == 404


async def test_clock_tolerates_unparseable_timestamps(client_factory, app_manager_instance):
    cache = K8sDbCache(session_maker=app_manager_instance.config.db.async_session_maker)
    session = session_object(str(uuid.uuid4()), state="Running", willHibernateAt="not a timestamp")
    session.manifest["spec"]["culling"]["lastInteraction"] = "13 o'clock"
    await cache.upsert(session)
    client, _ = client_factory(session)
    async with client as c:
        _, response = await c.get(URL.format(session_id=SESSION_ID), headers=role_headers())
    assert response.status_code == 200
    assert response.json["seconds_until_hibernate"] is None
    assert response.json["seconds_since_last_interaction"] is None
    assert response.json["alive"] is True
