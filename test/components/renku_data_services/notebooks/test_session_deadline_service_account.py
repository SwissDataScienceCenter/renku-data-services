"""The ssh-proxy service account may read and refresh SSH sessions on the public session routes."""

import dataclasses
import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sanic import Sanic
from ulid import ULID

from renku_data_services.app_config.config import SshProxyConfig
from renku_data_services.authn.dummy import DummyAuthenticator
from renku_data_services.base_api.error_handler import CustomErrorHandler
from renku_data_services.notebooks import apispec
from renku_data_services.notebooks.blueprints import NotebooksNewBP
from renku_data_services.notebooks.cr_amalthea_session import Size1
from renku_data_services.notebooks.crs import (
    AmaltheaSessionSpec,
    AmaltheaSessionV1Alpha1,
    Metadata,
    RequestsStr,
    Resources,
    Session,
    SessionType,
    State,
    Status,
    Storage,
)
from renku_data_services.session.models import FrontendVariant
from test.utils import SanicReusableASGITestClient

SESSION_NAME = "my-session"
OWNER_ID = "owner-user-id"
SESSION_URL = f"/api/data/sessions/{SESSION_NAME}"
MISSING_URL = "/api/data/sessions/does-not-exist"


def role_headers() -> dict[str, str]:
    token = json.dumps({"id": "service-account-ssh-proxy", "roles": ["ssh-proxy"], "is_admin": False})
    return {"Authorization": f"Bearer {token}"}


def user_headers(user_id: str = OWNER_ID) -> dict[str, str]:
    token = json.dumps({"id": user_id, "is_admin": False})
    return {"Authorization": f"Bearer {token}"}


def make_session(frontend_variant: str | None = FrontendVariant.ssh) -> AmaltheaSessionV1Alpha1:
    labels = {"renku.io/safe-username": OWNER_ID}
    if frontend_variant is not None:
        labels["renku.io/frontend-variant"] = frontend_variant
    return AmaltheaSessionV1Alpha1(
        metadata=Metadata(
            name=SESSION_NAME,
            labels=labels,
            annotations={
                "renku.io/resource_class_id": "1",
                "renku.io/project_id": str(ULID()),
                "renku.io/launcher_id": str(ULID()),
            },
        ),
        spec=AmaltheaSessionSpec(
            session=Session(
                image="renku/image:latest",
                urlPath=f"/sessions/{SESSION_NAME}",
                resources=Resources(requests={"cpu": RequestsStr("100m"), "memory": RequestsStr("1Gi")}),
                storage=Storage(size=Size1("1Gi")),
            ),
            hibernated=False,
            sessionType=SessionType.Interactive,
            ingress=None,
            authentication=None,
        ),
        status=Status(state=State.Running, url=None),
    )


class FakeK8sV2Client:
    """Only the session lookup and the merge patch matter here."""

    def __init__(self, session: AmaltheaSessionV1Alpha1 | None) -> None:
        self.session = session
        self.patches: list[tuple[str | None, dict]] = []

    async def get_session(self, name: str, safe_username: str | None) -> AmaltheaSessionV1Alpha1 | None:
        if self.session is None or name != self.session.metadata.name:
            return None
        if safe_username is not None and safe_username != OWNER_ID:
            return None
        return self.session

    async def patch_session(self, name: str, safe_username: str | None, patch: dict) -> AmaltheaSessionV1Alpha1:
        self.patches.append((safe_username, patch))
        assert self.session is not None
        return self.session


def make_client(session: AmaltheaSessionV1Alpha1 | None) -> tuple[SanicReusableASGITestClient, NotebooksNewBP, FakeK8sV2Client]:
    k8s = FakeK8sV2Client(session)
    mocks = {
        field.name: Mock()
        for field in dataclasses.fields(NotebooksNewBP)
        if field.name
        not in (
            "name",
            "url_prefix",
            "authenticator",
            "internal_gitlab_authenticator",
            "nb_config",
            "ssh_proxy_config",
            "request_middlewares",
            "response_middlewares",
        )
    }
    bp = NotebooksNewBP(
        name="notebooks",
        url_prefix="/api/data",
        authenticator=DummyAuthenticator(),
        internal_gitlab_authenticator=DummyAuthenticator(),
        nb_config=SimpleNamespace(k8s_v2_client=k8s),
        ssh_proxy_config=SshProxyConfig(
            enabled=True,
            hostname="ssh.renku.example.org",
            port=22,
            session_host_key_secret_name="host-secret",
            proxy_auth_key_secret_name="auth-secret",
        ),
        **mocks,
    )
    app = Sanic(f"test_session_deadline_{uuid.uuid4().hex}")
    app.blueprint(bp.blueprint())
    app.error_handler = CustomErrorHandler(apispec)
    return SanicReusableASGITestClient(app), bp, k8s


@pytest.fixture
def ssh_session() -> AmaltheaSessionV1Alpha1:
    return make_session()


async def test_get_with_role_returns_someone_elses_ssh_session(ssh_session):
    client, _, _ = make_client(ssh_session)
    async with client as c:
        _, response = await c.get(SESSION_URL, headers=role_headers())
    assert response.status_code == 200
    assert response.json["name"] == SESSION_NAME


async def test_get_with_role_on_non_ssh_session_is_404():
    client, _, _ = make_client(make_session(frontend_variant=FrontendVariant.vscodium))
    async with client as c:
        _, response = await c.get(SESSION_URL, headers=role_headers())
    assert response.status_code == 404


async def test_get_with_role_on_unknown_session_is_404():
    client, _, _ = make_client(None)
    async with client as c:
        _, response = await c.get(MISSING_URL, headers=role_headers())
    assert response.status_code == 404


async def test_get_without_role_keeps_the_owner_filter(ssh_session):
    client, _, _ = make_client(ssh_session)
    async with client as c:
        _, other = await c.get(SESSION_URL, headers=user_headers(str(uuid.uuid4())))
        _, owner = await c.get(SESSION_URL, headers=user_headers())
    assert other.status_code == 404
    assert owner.status_code == 200


async def test_patch_role_now_writes_only_last_interaction(ssh_session):
    client, _, k8s = make_client(ssh_session)
    async with client as c:
        _, response = await c.patch(SESSION_URL, headers=role_headers(), json={"lastInteraction": "now"})

    assert response.status_code == 200
    assert len(k8s.patches) == 1
    safe_username, patch = k8s.patches[0]
    assert safe_username is None
    assert set(patch) == {"spec"}
    assert set(patch["spec"]) == {"culling"}
    assert set(patch["spec"]["culling"]) == {"lastInteraction"}
    written = datetime.fromisoformat(patch["spec"]["culling"]["lastInteraction"].replace("Z", "+00:00"))
    assert abs((datetime.now(UTC) - written).total_seconds()) < 60


async def test_patch_role_hibernate_is_403_and_writes_nothing(ssh_session):
    client, _, k8s = make_client(ssh_session)
    async with client as c:
        _, response = await c.patch(SESSION_URL, headers=role_headers(), json={"state": "hibernated"})
    assert response.status_code == 403
    assert k8s.patches == []


async def test_patch_role_explicit_timestamp_is_403(ssh_session):
    """Backdating lastInteraction would hibernate the session, so only "now" is allowed."""
    client, _, k8s = make_client(ssh_session)
    async with client as c:
        _, response = await c.patch(
            SESSION_URL, headers=role_headers(), json={"lastInteraction": "2020-01-01T00:00:00Z"}
        )
    assert response.status_code == 403
    assert k8s.patches == []


async def test_patch_role_extra_field_is_403(ssh_session):
    client, _, k8s = make_client(ssh_session)
    async with client as c:
        _, response = await c.patch(
            SESSION_URL, headers=role_headers(), json={"lastInteraction": "now", "resource_class_id": 3}
        )
    assert response.status_code == 403
    assert k8s.patches == []


async def test_patch_role_non_ssh_session_is_404():
    client, _, k8s = make_client(make_session(frontend_variant=FrontendVariant.vscodium))
    async with client as c:
        _, response = await c.patch(SESSION_URL, headers=role_headers(), json={"lastInteraction": "now"})
    assert response.status_code == 404
    assert k8s.patches == []


async def test_patch_role_unknown_session_is_404():
    client, _, k8s = make_client(None)
    async with client as c:
        _, response = await c.patch(MISSING_URL, headers=role_headers(), json={"lastInteraction": "now"})
    assert response.status_code == 404
    assert k8s.patches == []
