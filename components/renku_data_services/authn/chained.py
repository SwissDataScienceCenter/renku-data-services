"""Authenticator which tries authenticators in a chain until a user is authenticated or all authenticators are tried."""

from collections.abc import Sequence
from dataclasses import dataclass

from sanic import Request

from renku_data_services.base_models.core import (
    AnyAPIUser,
    Authenticator,
)
from renku_data_services.errors import errors


@dataclass(frozen=True, kw_only=True)
class ChainedAuthenticator(Authenticator[AnyAPIUser]):
    """Chain authenticators until a user is authenticated or all authenticators are tried."""

    token_field: str = "__not_used__"
    chain: Sequence[Authenticator[AnyAPIUser]]

    def __post_init__(self) -> None:
        if not self.chain:
            raise errors.ProgrammingError(message="Authenticator chain needs to have at least one authenticator.")

    async def authenticate(self, access_token: str, request: Request) -> AnyAPIUser:
        """Authenticate by going through the authenticator chain."""

        user: AnyAPIUser | None = None
        for auth in self.chain:
            user = await auth.authenticate(access_token=access_token, request=request)
            if user.is_authenticated:
                return user

        # NOTE: user is not None since there is at least one authenticator in the chain
        assert user is not None
        return user
