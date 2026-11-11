"""Internal SSH proxy blueprint."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sanic import HTTPResponse, Request, json
from sanic.response import JSONResponse
from sanic_ext import validate

from renku_data_services import base_models, errors
from renku_data_services.base_api.auth import authenticate, require_role
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.k8s.client_interfaces import K8sClient
from renku_data_services.k8s.db import K8sDbCache
from renku_data_services.k8s.models import K8sObject, K8sObjectFilter
from renku_data_services.notebooks.constants import AMALTHEA_SESSION_GVK
from renku_data_services.ssh_proxy import apispec
from renku_data_services.users.core import fingerprint_ssh_public_key
from renku_data_services.users.db import SSHKeyRepository


@dataclass(kw_only=True)
class SSHProxyBP(CustomBlueprint):
    """Internal endpoints consumed by the Renku SSH proxy."""

    ssh_key_repo: SSHKeyRepository
    k8s_db_cache: K8sDbCache

    def authorize(self) -> BlueprintFactoryResponse:
        """Authorize a connection from an SSH public key and a session id."""

        @validate(json=apispec.SessionAuthorizeRequest)
        async def _authorize(_: Request, body: apispec.SessionAuthorizeRequest, session_id: str) -> HTTPResponse:
            fingerprint = fingerprint_ssh_public_key(body.public_key)
            user_id = await self.ssh_key_repo.get_user_id_by_fingerprint(fingerprint) if fingerprint else None
            if user_id is None:
                # NOTE: malformed and unknown keys are both a plain "no", so the proxy has one failure branch.
                raise errors.MissingResourceError(message="No registered SSH key matches the provided key.")
            sessions = [
                obj
                async for obj in self.k8s_db_cache.list(
                    K8sObjectFilter(gvk=AMALTHEA_SESSION_GVK, name=session_id, user_id=user_id)
                )
            ]
            if not sessions:
                raise errors.MissingResourceError(message="The session does not exist or is not accessible.")
            return HTTPResponse(status=204)

        return "/internal/sessions/<session_id>/authorize", ["POST"], _authorize


def _parse_timestamp(value: Any) -> datetime:
    """Parse an RFC3339 timestamp from a manifest into an aware datetime."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


@dataclass(kw_only=True)
class SSHSessionInteractionBP(CustomBlueprint):
    """Internal session-clock endpoints consumed by the Renku SSH proxy."""

    authenticator: base_models.Authenticator
    k8s_db_cache: K8sDbCache
    k8s_client: K8sClient
    ssh_proxy_role: str = "ssh-proxy"

    async def _ssh_session(self, session_id: str) -> K8sObject:
        """Return the SSH session with this name, or raise a 404.

        The caller is a service, so there is no user filter; the label keeps
        non-SSH sessions out of reach.
        """
        sessions = self.k8s_db_cache.list(
            K8sObjectFilter(
                gvk=AMALTHEA_SESSION_GVK,
                name=session_id,
                label_selector={"renku.io/frontend-variant": "ssh"},
            )
        )
        session = await anext(aiter(sessions), None)
        if session is None:
            raise errors.MissingResourceError(message="The session does not exist or is not an SSH session.")
        return session

    def touch(self) -> BlueprintFactoryResponse:
        """Touch a session's cull clock."""

        @authenticate(self.authenticator)
        @require_role(self.ssh_proxy_role)
        async def _touch(_: Request, _user: base_models.APIUser, session_id: str) -> HTTPResponse:
            session = await self._ssh_session(session_id)
            now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            await self.k8s_client.patch(session, {"spec": {"culling": {"lastInteraction": now}}})
            return HTTPResponse(status=204)

        return "/internal/sessions/<session_id>/interaction", ["POST"], _touch

    def clock(self) -> BlueprintFactoryResponse:
        """Read a session's cull clock."""

        @authenticate(self.authenticator)
        @require_role(self.ssh_proxy_role)
        async def _clock(_: Request, _user: base_models.APIUser, session_id: str) -> JSONResponse:
            cached = await self._ssh_session(session_id)
            session = await self.k8s_client.get(cached)
            if session is None:
                raise errors.MissingResourceError(message="The session does not exist or is not an SSH session.")
            status = session.manifest.get("status") or {}
            culling = session.manifest.get("spec", {}).get("culling") or {}
            now = datetime.now(UTC)
            deadline = status.get("willHibernateAt")
            last_interaction = culling.get("lastInteraction")
            remaining = None if deadline is None else max(0, int((_parse_timestamp(deadline) - now).total_seconds()))
            since_input = (
                None
                if last_interaction is None
                else max(0, int((now - _parse_timestamp(last_interaction)).total_seconds()))
            )
            alive = status.get("state") in ("Running", "RunningDegraded")
            return json(
                {
                    "seconds_until_hibernate": remaining,
                    "seconds_since_last_interaction": since_input,
                    "alive": alive,
                }
            )

        return "/internal/sessions/<session_id>/interaction", ["GET"], _clock
