"""Internal SSH proxy blueprint."""

from dataclasses import dataclass

from sanic import Request
from sanic.response import JSONResponse
from sanic_ext import validate

from renku_data_services.app_config import logging
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_models.validation import validated_json
from renku_data_services.ssh_proxy import apispec
from renku_data_services.ssh_proxy.core import SessionAuthorize

logger = logging.getLogger(__file__)


@dataclass(kw_only=True)
class SSHProxyBP(CustomBlueprint):
    """Internal endpoints consumed by the Renku SSH proxy."""

    authorizer: SessionAuthorize

    def authorize(self) -> BlueprintFactoryResponse:
        """Authorize a connection from an SSH public key and a session id."""

        @validate(json=apispec.SessionAuthorizeRequest)
        async def _authorize(_: Request, body: apispec.SessionAuthorizeRequest, session_id: str) -> JSONResponse:
            session_data = await self.authorizer.authorize_session(body.public_key, session_id)
            result = apispec.SessionAuthorizeResponse(
                target_host=session_data.target_host,
                target_port=session_data.target_port,
                target_user=session_data.target_user,
                host_key_pub=session_data.host_key_pub,
                auth_key_priv=session_data.auth_key_priv,
            )
            return validated_json(apispec.SessionAuthorizeResponse, result)

        return "/internal/sessions/<session_id>/authorize", ["POST"], _authorize
