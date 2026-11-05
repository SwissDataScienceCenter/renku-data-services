from dataclasses import dataclass

from kubernetes.client import V1ObjectMeta, V1Secret

from renku_data_services.base_models import RESET
from renku_data_services.notebooks.core_sessions import _make_patch_spec_list
from renku_data_services.notebooks.crs import (
    AmaltheaSessionV1Alpha1Patch,
    AmaltheaSessionV1Alpha1SpecPatch,
    Authentication,
    AuthenticationType,
    Ingress,
)
from renku_data_services.notebooks.models import ExtraSecret


def test_make_patch_spec_list() -> None:
    @dataclass(eq=True)
    class MyResource:
        name: str
        contents: str

    existing = [
        MyResource(name="first", contents="first content"),
        MyResource(name="second", contents="second content"),
    ]
    updated = [
        MyResource(name="second", contents="second content patched"),
        MyResource(name="third", contents="new third content"),
    ]
    patch_list = _make_patch_spec_list(existing=existing, updated=updated)

    assert patch_list == [
        MyResource(name="first", contents="first content"),
        MyResource(name="second", contents="second content patched"),
        MyResource(name="third", contents="new third content"),
    ]


def test_session_patch_serializes_authentication_with_secret_ref_subclass() -> None:
    """Regression test: resuming a session used to send `authentication: null` and remove the authentication.

    `ExtraSecret.key_ref()` returns `crs.SecretRef`, a subclass of the generated `SecretRef`. That made
    the `Authentication` member of the `Authentication | ResetType | None` union fail pydantic's strict
    serialization check, and the catch-all `ResetType` serializer turned the value into None.
    """
    auth_secret = ExtraSecret(V1Secret(metadata=V1ObjectMeta(name="session-name"), string_data={"auth": "data"}))
    authentication = Authentication(
        enabled=True,
        type=AuthenticationType.oauth2proxy,
        secretRef=auth_secret.key_ref("auth"),
    )
    ingress = Ingress(host="renku.example.org", pathPrefix="/sessions/session-name")
    patch = AmaltheaSessionV1Alpha1Patch(
        spec=AmaltheaSessionV1Alpha1SpecPatch(authentication=authentication, ingress=ingress)
    )

    serialized = patch.to_rfc7386()

    assert serialized["spec"]["authentication"] == {
        "enabled": True,
        "type": "oauth2proxy",
        "secretRef": {"name": "session-name", "key": "auth", "adopt": True},
    }
    assert serialized["spec"]["ingress"]["host"] == "renku.example.org"
    assert serialized["spec"]["ingress"]["pathPrefix"] == "/sessions/session-name"


def test_session_patch_reset_and_unset_fields() -> None:
    """RESET must serialize to null (delete the field) and None must be omitted (leave the field unchanged)."""
    patch = AmaltheaSessionV1Alpha1Patch(spec=AmaltheaSessionV1Alpha1SpecPatch(authentication=RESET))

    serialized = patch.to_rfc7386()

    assert serialized["spec"]["authentication"] is None
    assert "ingress" not in serialized["spec"]
