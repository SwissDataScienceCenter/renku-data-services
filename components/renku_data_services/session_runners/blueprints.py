"""Session runners blueprints."""

from collections.abc import Callable
from dataclasses import dataclass

from sanic import Request
from sanic.response import HTTPResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from renku_data_services import base_models
from renku_data_services.authn.renku import RenkuSelfAuthenticator, RenkuSelfTokenMint
from renku_data_services.base_api.auth import authenticate, only_authenticated
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.misc import validate, validate_query
from renku_data_services.base_models.validation import validated_json
from renku_data_services.notebooks import models as nb_models
from renku_data_services.session_runners import apispec
from renku_data_services.session_runners.core import (
    get_runner_scope,
    validate_patch_assigned_session_secrets,
    validate_session_runner_patch,
    validate_unsaved_session_runner,
)
from renku_data_services.session_runners.db import UserSessionRunnersRepository


@dataclass(kw_only=True)
class UserSessionRunnersBP(CustomBlueprint):
    """Handlers for user-scoped session runners."""

    runners_repo: UserSessionRunnersRepository
    authenticator: base_models.Authenticator
    internal_authenticator: RenkuSelfAuthenticator
    internal_token_mint: RenkuSelfTokenMint
    session_maker: Callable[..., AsyncSession]

    def get_all_user_session_runners(self) -> BlueprintFactoryResponse:
        """Get all user-scoped session runners."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate_query(query=apispec.SessionRunnersUserGetParametersQuery)
        async def _get_all_user_session_runners(
            _: Request, user: base_models.APIUser, query: apispec.SessionRunnersUserGetParametersQuery
        ) -> JSONResponse:
            all_users = query.all_users or False
            async with self.session_maker() as session, session.begin():
                runners = self.runners_repo.get_all_runners(session=session, user=user, all_users=all_users)
                result = [item async for item in runners]
            return validated_json(apispec.UserSessionRunners, result)

        return "/session_runners/user", ["GET"], _get_all_user_session_runners

    def post_user_session_runner(self) -> BlueprintFactoryResponse:
        """Create a new user-scoped session runner."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.UserSessionRunnerPost)
        async def _post_user_session_runner(
            _: Request, user: base_models.APIUser, body: apispec.UserSessionRunnerPost
        ) -> JSONResponse:
            new_runner = validate_unsaved_session_runner(runner=body)
            async with self.session_maker() as session, session.begin():
                runner = await self.runners_repo.insert_runner(session=session, user=user, runner=new_runner)
            return validated_json(apispec.UserSessionRunner, runner, status=201)

        return "/session_runners/user", ["POST"], _post_user_session_runner

    def post_register_user_session_runner(self) -> BlueprintFactoryResponse:
        """Register a user-scoped session runner."""

        @validate(json=apispec.UserSessionRunnerRegisterPost)
        async def _post_register_user_session_runner(
            _: Request, body: apispec.UserSessionRunnerRegisterPost
        ) -> JSONResponse:
            registration_token = body.registration_token
            async with self.session_maker() as session, session.begin():
                runner, user = await self.runners_repo.register_runner(
                    session=session, registration_token=registration_token
                )
            internal_token_scope = f"user_runner:{str(runner.id)}"
            internal_access_token = self.internal_token_mint.create_access_token(user=user, scope=internal_token_scope)
            internal_refresh_token = self.internal_token_mint.create_refresh_token(
                user=user, scope=internal_token_scope
            )
            auth: dict[str, str | int] = {
                "access_token": internal_access_token,
                "token_type": "Bearer",
                "expires_in": int(self.internal_token_mint.default_access_token_expiration.total_seconds()),
                "refresh_token": internal_refresh_token,
                "refresh_expires_in": int(self.internal_token_mint.default_refresh_token_expiration.total_seconds()),
                "scope": internal_token_scope,
            }
            return validated_json(apispec.UserSessionRunnerRegisterResponse, {"runner": runner, "auth": auth})

        return "/session_runners/user/register", ["POST"], _post_register_user_session_runner

    def get_user_session_runner(self) -> BlueprintFactoryResponse:
        """Get a user-scoped session runner."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _get_user_session_runner(
            _: Request, user: base_models.APIUser, session_runner_id: ULID
        ) -> JSONResponse:
            async with self.session_maker() as session, session.begin():
                runner = await self.runners_repo.get_runner(session=session, user=user, runner_id=session_runner_id)
            return validated_json(apispec.UserSessionRunner, runner)

        return "/session_runners/user/<session_runner_id:ulid>", ["GET"], _get_user_session_runner

    def patch_user_session_runner(self) -> BlueprintFactoryResponse:
        """Update a user-scoped session runner."""

        @authenticate(self.internal_authenticator)
        @only_authenticated
        @validate(json=apispec.UserSessionRunnerPatch)
        async def _patch_user_session_runner(
            _: Request, user: base_models.APIUser, session_runner_id: ULID, body: apispec.UserSessionRunnerPatch
        ) -> JSONResponse:
            patch = validate_session_runner_patch(patch=body)
            async with self.session_maker() as session, session.begin():
                runner = await self.runners_repo.update_runner(
                    session=session, user=user, runner_id=session_runner_id, patch=patch
                )
            return validated_json(apispec.UserSessionRunner, runner)

        return "/session_runners/user/<session_runner_id:ulid>", ["PATCH"], _patch_user_session_runner

    def delete_user_session_runner(self) -> BlueprintFactoryResponse:
        """Remove a user-scoped session runner."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete_user_session_runner(
            _: Request, user: base_models.APIUser, session_runner_id: ULID
        ) -> HTTPResponse:
            async with self.session_maker() as session, session.begin():
                await self.runners_repo.delete_runner(session=session, user=user, runner_id=session_runner_id)
            return HTTPResponse(status=204)

        return "/session_runners/user/<session_runner_id:ulid>", ["DELETE"], _delete_user_session_runner

    def get_all_user_sessions(self) -> BlueprintFactoryResponse:
        """List sessions which are powered by user-scoped runners."""

        @authenticate(self.internal_authenticator)
        @only_authenticated
        async def _get_all_user_sessions(_: Request, user: base_models.APIUser) -> HTTPResponse:
            runner_id = get_runner_scope(user)
            async with self.session_maker() as session, session.begin():
                renku_sessions = self.runners_repo.get_all_remote_sessions(
                    session=session, user=user, runner_id=runner_id
                )
                result = [item async for item in renku_sessions]
            return validated_json(apispec.RemoteUserSessions, result)

        return "/session_runners/user/sessions", ["GET"], _get_all_user_sessions

    def get_user_session(self) -> BlueprintFactoryResponse:
        """Get a session which is powered by a user-scoped runner."""

        @authenticate(self.internal_authenticator)
        @only_authenticated
        async def _get_user_session(_: Request, user: base_models.APIUser, session_id: str) -> HTTPResponse:
            runner_id = get_runner_scope(user)
            async with self.session_maker() as session, session.begin():
                renku_session = await self.runners_repo.get_remote_session(
                    session=session, user=user, renku_session_id=session_id, runner_id=runner_id
                )
            return validated_json(apispec.RemoteUserSession, renku_session)

        return "/session_runners/user/sessions/<session_id>", ["GET"], _get_user_session

    def get_user_session_spec(self) -> BlueprintFactoryResponse:
        """Get the spec of a session which is powered by a user-scoped runner."""

        @authenticate(self.internal_authenticator)
        @only_authenticated
        async def _get_user_session_spec(_: Request, user: base_models.APIUser, session_id: str) -> HTTPResponse:
            runner_id = get_runner_scope(user)
            async with self.session_maker() as session, session.begin():
                renku_session = await self.runners_repo.get_remote_session(
                    session=session, user=user, renku_session_id=session_id, runner_id=runner_id
                )
            k8s_session = await self.runners_repo.get_remote_session_spec(user=user, renku_session_id=session_id)
            response = apispec.RemoteUserSessionWithSpec(
                session_id=renku_session.session_id,
                user_id=renku_session.user_id,
                resource_pool_id=renku_session.resource_pool_id,
                runner_id=str(renku_session.runner_id) if renku_session.runner_id else None,
                spec=apispec.RemoteUserSessionSpec(
                    image=k8s_session.spec.session.image,
                    url=k8s_session.base_url() or "None",
                    session_type=nb_models.SessionType.interactive.value,
                    command=list(k8s_session.spec.session.command) if k8s_session.spec.session.command else [],
                    args=list(k8s_session.spec.session.args) if k8s_session.spec.session.args else [],
                ),
            )
            return validated_json(apispec.RemoteUserSessionWithSpec, response)

        return "/session_runners/user/sessions/<session_id>/spec", ["GET"], _get_user_session_spec

    def get_user_session_secrets(self) -> BlueprintFactoryResponse:
        """Get the secrets necessary to run a remote Renku session."""

        @authenticate(self.internal_authenticator)
        @only_authenticated
        async def _get_user_session_secrets(_: Request, user: base_models.APIUser, session_id: str) -> HTTPResponse:
            runner_id = get_runner_scope(user)
            async with self.session_maker() as session, session.begin():
                secrets = await self.runners_repo.get_remote_session_secrets(
                    session=session, user=user, renku_session_id=session_id, runner_id=runner_id
                )
            return validated_json(apispec.RemoteUserSessionSecrets, secrets)

        return "/session_runners/user/sessions/<session_id>/secrets", ["GET"], _get_user_session_secrets

    def patch_user_session_secrets(self) -> BlueprintFactoryResponse:
        """Update the secrets used in a remote Renku session."""

        @authenticate(self.internal_authenticator)
        @only_authenticated
        @validate(json=apispec.RemoteUserSessionSecrets)
        async def _patch_user_session_secrets(
            _: Request, user: base_models.APIUser, session_id: str, body: apispec.RemoteUserSessionSecrets
        ) -> HTTPResponse:
            runner_id = get_runner_scope(user)
            update = validate_patch_assigned_session_secrets(patch=body)
            async with self.session_maker() as session, session.begin():
                secrets = await self.runners_repo.update_remote_session_secrets(
                    session=session, user=user, renku_session_id=session_id, runner_id=runner_id, update=update
                )
            return validated_json(apispec.RemoteUserSessionSecrets, secrets)

        return "/session_runners/user/sessions/<session_id>/secrets", ["PATCH"], _patch_user_session_secrets
