"""Internal authentication blueprint."""

from dataclasses import dataclass

from sanic import Request
from sanic.response import JSONResponse

from renku_data_services import base_models
from renku_data_services.app_config import logging
from renku_data_services.authn.renku import RenkuSelfTokenMint
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint

logger = logging.getLogger(__name__)


@dataclass(kw_only=True)
class InternalAuthenticationBP(CustomBlueprint):
    """Handlers for internal authentication."""

    authenticator: base_models.Authenticator[base_models.APIUser]
    internal_token_mint: RenkuSelfTokenMint

    def post_token(self) -> BlueprintFactoryResponse:
        """Obtain a fresh internal token."""

        # @authenticate(self.authenticator)
        # @only_authenticated
        async def _post_token(request: Request, user: base_models.APIUser) -> JSONResponse:
            raise NotImplementedError()
            # parsed_access_token: dict[str, Any] | None = None
            # with suppress(AttributeError):
            #     expected_authenticator = (
            #         f"{self.authenticator.__class__.__module__}.{self.authenticator.__class__.__qualname__}"
            #     )
            #     if request.ctx.renku_authenticator != expected_authenticator:
            #         raise errors.ProgrammingError(
            #             message=f"Expected authenticator class to be {expected_authenticator}."
            #         )
            #     parsed_access_token = request.ctx.renku_parsed_access_token
            # if parsed_access_token is None:
            #     raise errors.ProgrammingError(
            #         message="Unexpected error: could not get parsed access token from authenticator."
            #     )

            # scope = str(parsed_access_token.get("scope", ""))
            # scopes = scope.split(" ")

            # # TODO: verify session if scope found
            # logger.info(f"Got scopes = {scopes}")

            # new_token = self.internal_token_mint.create_token(user=user, scope=scope)
            # return validated_json(
            #     apispec.InternalPostTokenResponse,
            #     {
            #         "access_token": new_token,
            #         "token_type": apispec.InternalTokenType.Bearer,
            #         "expires_in": int(self.internal_token_mint.default_token_expiration.total_seconds()),
            #     },
            # )

        return "/internal/authentication/token", ["POST"], _post_token
