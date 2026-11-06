"""Tests for detecting SSH sessions and computing their URL from the Amalthea session manifest."""

from typing import Any

import pytest
from kubernetes.client import V1ObjectMeta, V1Secret
from ulid import ULID

from renku_data_services.app_config.config import SshProxyConfig
from renku_data_services.notebooks.cr_amalthea_session import Size1
from renku_data_services.notebooks.crs import (
    AmaltheaSessionSpec,
    AmaltheaSessionV1Alpha1,
    Authentication,
    AuthenticationType,
    Ingress,
    Metadata,
    RequestsStr,
    Resources,
    Session,
    SessionType,
    State,
    Status,
    Storage,
)
from renku_data_services.notebooks.models import ExtraSecret
from renku_data_services.session.models import FrontendVariant

SESSION_NAME = "my-session"


def _ssh_config(enabled: bool = True, port: int = 22) -> SshProxyConfig:
    return SshProxyConfig(
        enabled=enabled,
        hostname="ssh.renku.example.org",
        port=port,
        session_host_key_secret_name="host-secret",
        proxy_auth_key_secret_name="auth-secret",
    )


def _session(
    frontend_variant: str | None = FrontendVariant.ssh,
    session_type: SessionType = SessionType.Interactive,
    with_ingress: bool = False,
    with_authentication: bool = False,
    status_url: str | None = None,
) -> AmaltheaSessionV1Alpha1:
    labels = {"renku.io/safe-username": "user-id"}
    if frontend_variant is not None:
        labels["renku.io/frontend-variant"] = frontend_variant
    ingress = Ingress(host="renku.example.org", pathPrefix=f"/sessions/{SESSION_NAME}") if with_ingress else None
    authentication = None
    if with_authentication:
        auth_secret = ExtraSecret(V1Secret(metadata=V1ObjectMeta(name=SESSION_NAME), string_data={"auth": "data"}))
        authentication = Authentication(
            enabled=True, type=AuthenticationType.oauth2proxy, secretRef=auth_secret.key_ref("auth")
        )
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
            sessionType=session_type,
            ingress=ingress,
            authentication=authentication,
        ),
        status=Status(state=State.Running, url=status_url),
    )


@pytest.mark.parametrize(
    "session_kwargs,expected",
    [
        pytest.param({}, True, id="ssh-session"),
        pytest.param({"frontend_variant": None}, False, id="missing-label"),
        pytest.param({"frontend_variant": "not-a-frontend"}, False, id="invalid-label"),
        pytest.param({"frontend_variant": FrontendVariant.vscodium}, False, id="http-frontend-label"),
        pytest.param({"session_type": SessionType.NonInteractive}, False, id="non-interactive"),
        pytest.param({"with_ingress": True}, False, id="ssh-label-with-ingress"),
        pytest.param({"with_authentication": True}, False, id="ssh-label-with-authentication"),
    ],
)
def test_likely_ssh(session_kwargs: dict[str, Any], expected: bool) -> None:
    assert _session(**session_kwargs).likely_ssh() is expected


_HTTP_SESSION = {"with_ingress": True, "with_authentication": True}


@pytest.mark.parametrize(
    "session_kwargs,ssh_config_kwargs,expected_url",
    [
        pytest.param({}, {"port": 22}, f"ssh://{SESSION_NAME}@ssh.renku.example.org", id="ssh-default-port"),
        pytest.param({}, {"port": 2222}, f"ssh://{SESSION_NAME}@ssh.renku.example.org:2222", id="ssh-custom-port"),
        # Amalthea's status URL is for HTTP access and must not leak into SSH sessions
        pytest.param(
            {"status_url": "https://renku.example.org/sessions/my-session"},
            {},
            f"ssh://{SESSION_NAME}@ssh.renku.example.org",
            id="ssh-ignores-status-url",
        ),
        pytest.param({}, {"enabled": False}, "None", id="ssh-disabled"),
        # Sessions with an ingress get the HTTP URL, even if the label says ssh
        pytest.param(
            {**_HTTP_SESSION, "frontend_variant": FrontendVariant.vscodium},
            {},
            f"http://renku.example.org/sessions/{SESSION_NAME}/",
            id="http-vscodium-label",
        ),
        pytest.param(
            {**_HTTP_SESSION, "frontend_variant": FrontendVariant.ssh},
            {},
            f"http://renku.example.org/sessions/{SESSION_NAME}/",
            id="http-ssh-label",
        ),
        pytest.param(
            {**_HTTP_SESSION, "frontend_variant": None},
            {},
            f"http://renku.example.org/sessions/{SESSION_NAME}/",
            id="http-no-label",
        ),
        pytest.param(
            {
                **_HTTP_SESSION,
                "frontend_variant": FrontendVariant.vscodium,
                "status_url": "https://renku.example.org/from-status",
            },
            {},
            "https://renku.example.org/from-status",
            id="http-prefers-status-url",
        ),
    ],
)
def test_as_apispec_url(session_kwargs: dict[str, Any], ssh_config_kwargs: dict[str, Any], expected_url: str) -> None:
    assert _session(**session_kwargs).as_apispec(_ssh_config(**ssh_config_kwargs)).url == expected_url
