"""Internal authentication blueprint."""

from dataclasses import dataclass

from sanic import Request
from sanic.response import JSONResponse
from sanic_ext import validate

from renku_data_services import base_models, errors
from renku_data_services.app_config import logging
from renku_data_services.authn.api import apispec
from renku_data_services.authn.renku import RenkuSelfAuthenticator, RenkuSelfTokenMint, TokenType
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_models.validation import validated_json

logger = logging.getLogger(__name__)


@dataclass(kw_only=True)
class InternalAuthenticationBP(CustomBlueprint):
    """Handlers for internal authentication."""

    internal_authenticator: RenkuSelfAuthenticator
    internal_token_mint: RenkuSelfTokenMint

    def post_token(self) -> BlueprintFactoryResponse:
        """Token endpoint for internal authentication.

        Supports refreshing internal authentication tokens.
        """

        @validate(form=apispec.PostTokenRequest)
        async def _post_token(request: Request, body: apispec.PostTokenRequest) -> JSONResponse:
            parsed_token = await self.internal_authenticator.verify_refresh_token(refresh_token=body.refresh_token)
            if parsed_token is None:
                raise errors.UnauthorizedError(message="You have to be authenticated to perform this operation.")

            user = base_models.AuthenticatedAPIUser(
                is_admin=False,
                id=parsed_token["sub"],
                access_token="",  # nosec B106
                full_name=parsed_token.get("name"),
                first_name=parsed_token.get("given_name"),
                last_name=parsed_token.get("family_name"),
                email=parsed_token["email"],
                access_token_expires_at=None,
                roles=[],
            )

            scope = str(parsed_token.get("scope", ""))
            scopes = scope.split(" ")

            # TODO: verify session if scope found
            logger.info(f"Got scopes = {scopes}")

            new_access_token = self.internal_token_mint.create_access_token(user=user, scope=scope)
            new_refresh_token = self.internal_token_mint.create_refresh_token(user=user, scope=scope)
            token_type: TokenType = "Bearer"
            return validated_json(
                apispec.PostTokenResponse,
                {
                    "access_token": new_access_token,
                    "token_type": token_type,
                    "expires_in": int(self.internal_token_mint.default_access_token_expiration.total_seconds()),
                    "refresh_token": new_refresh_token,
                    "refresh_expires_in": int(
                        self.internal_token_mint.default_refresh_token_expiration.total_seconds()
                    ),
                    "scope": scope,
                },
            )

        return "/internal/authentication/token", ["POST"], _post_token
