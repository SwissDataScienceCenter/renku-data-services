"""Internal SSH proxy blueprint."""

from dataclasses import dataclass

from sanic import HTTPResponse, Request
from sanic.response import JSONResponse
from sanic_ext import validate

from renku_data_services import errors
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_models.validation import validated_json
from renku_data_services.notebooks.config import NotebooksConfig
from renku_data_services.ssh_proxy import apispec
from renku_data_services.users.core import fingerprint_ssh_public_key
from renku_data_services.users.db import SSHKeyRepository


@dataclass(kw_only=True)
class SSHProxyBP(CustomBlueprint):
    """Internal endpoints consumed by the Renku SSH proxy."""

    ssh_key_repo: SSHKeyRepository
    nb_config: NotebooksConfig

    def identity(self) -> BlueprintFactoryResponse:
        """Resolve the Renku user that owns an SSH public key."""

        @validate(json=apispec.SSHKeyIdentityRequest)
        async def _identity(_: Request, body: apispec.SSHKeyIdentityRequest) -> JSONResponse:
            fingerprint = fingerprint_ssh_public_key(body.public_key)
            user_id = await self.ssh_key_repo.get_user_id_by_fingerprint(fingerprint) if fingerprint else None
            if user_id is None:
                # NOTE: malformed and unknown keys are both a plain "no", so the proxy has one failure branch.
                raise errors.MissingResourceError(message="No registered SSH key matches the provided key.")
            return validated_json(apispec.SSHKeyIdentityResponse, {"user_id": user_id})

        return "/internal/ssh_keys/identity", ["POST"], _identity

    def authorize(self) -> BlueprintFactoryResponse:
        """Check whether a user may open a session."""

        async def _authorize(request: Request, session_id: str) -> HTTPResponse:
            user_id = request.args.get("user_id")
            if not user_id:
                raise errors.ValidationError(message="The user_id query parameter is required.")
            session = await self.nb_config.k8s_v2_client.get_session(session_id, user_id)
            if session is None:
                raise errors.MissingResourceError(message="The session does not exist or is not accessible.")
            return HTTPResponse(status=204)

        return "/internal/sessions/<session_id>/authorize", ["GET"], _authorize
