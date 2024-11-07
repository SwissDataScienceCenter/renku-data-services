"""Session blueprint."""

from dataclasses import dataclass

from sanic import HTTPResponse, Request
from sanic.response import JSONResponse
from sanic_ext import validate
from ulid import ULID

from renku_data_services import base_models
from renku_data_services.base_api.auth import authenticate, only_authenticated
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.misc import validate_body_root_model
from renku_data_services.base_models.validation import validated_json
from renku_data_services.session import apispec, models
from renku_data_services.session.core import (
    validate_environment_patch,
    validate_session_launcher_patch,
    validate_session_launcher_secret_slot_patch,
    validate_session_launcher_secrets_patch,
    validate_unsaved_environment,
    validate_unsaved_session_launcher,
    validate_unsaved_session_launcher_secret_slot,
)
from renku_data_services.session.db import SessionRepository, SessionSecretRepository


@dataclass(kw_only=True)
class EnvironmentsBP(CustomBlueprint):
    """Handlers for manipulating session environments."""

    session_repo: SessionRepository
    authenticator: base_models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """List all session environments."""

        async def _get_all(_: Request) -> JSONResponse:
            environments = await self.session_repo.get_environments()
            return validated_json(apispec.EnvironmentList, environments)

        return "/environments", ["GET"], _get_all

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific session environment."""

        async def _get_one(_: Request, environment_id: ULID) -> JSONResponse:
            environment = await self.session_repo.get_environment(environment_id=environment_id)
            return validated_json(apispec.Environment, environment)

        return "/environments/<environment_id:ulid>", ["GET"], _get_one

    def post(self) -> BlueprintFactoryResponse:
        """Create a new session environment."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.EnvironmentPost)
        async def _post(_: Request, user: base_models.APIUser, body: apispec.EnvironmentPost) -> JSONResponse:
            new_environment = validate_unsaved_environment(body, models.EnvironmentKind.GLOBAL)
            environment = await self.session_repo.insert_environment(user=user, environment=new_environment)
            return validated_json(apispec.Environment, environment, status=201)

        return "/environments", ["POST"], _post

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update a specific session environment."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.EnvironmentPatch)
        async def _patch(
            _: Request, user: base_models.APIUser, environment_id: ULID, body: apispec.EnvironmentPatch
        ) -> JSONResponse:
            environment_patch = validate_environment_patch(body)
            environment = await self.session_repo.update_environment(
                user=user, environment_id=environment_id, patch=environment_patch
            )
            return validated_json(apispec.Environment, environment)

        return "/environments/<environment_id:ulid>", ["PATCH"], _patch

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific session environment."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete(_: Request, user: base_models.APIUser, environment_id: ULID) -> HTTPResponse:
            await self.session_repo.delete_environment(user=user, environment_id=environment_id)
            return HTTPResponse(status=204)

        return "/environments/<environment_id:ulid>", ["DELETE"], _delete


@dataclass(kw_only=True)
class SessionLaunchersBP(CustomBlueprint):
    """Handlers for manipulating session launchers."""

    session_repo: SessionRepository
    authenticator: base_models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """List all session launcher visible to user."""

        @authenticate(self.authenticator)
        async def _get_all(_: Request, user: base_models.APIUser) -> JSONResponse:
            launchers = await self.session_repo.get_launchers(user=user)
            return validated_json(apispec.SessionLaunchersList, launchers)

        return "/session_launchers", ["GET"], _get_all

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific session launcher."""

        @authenticate(self.authenticator)
        async def _get_one(_: Request, user: base_models.APIUser, launcher_id: ULID) -> JSONResponse:
            launcher = await self.session_repo.get_launcher(user=user, launcher_id=launcher_id)
            return validated_json(apispec.SessionLauncher, launcher)

        return "/session_launchers/<launcher_id:ulid>", ["GET"], _get_one

    def post(self) -> BlueprintFactoryResponse:
        """Create a new session launcher."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.SessionLauncherPost)
        async def _post(_: Request, user: base_models.APIUser, body: apispec.SessionLauncherPost) -> JSONResponse:
            new_launcher = validate_unsaved_session_launcher(body)
            launcher = await self.session_repo.insert_launcher(user=user, launcher=new_launcher)
            return validated_json(apispec.SessionLauncher, launcher, status=201)

        return "/session_launchers", ["POST"], _post

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update a specific session launcher."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.SessionLauncherPatch)
        async def _patch(
            _: Request, user: base_models.APIUser, launcher_id: ULID, body: apispec.SessionLauncherPatch
        ) -> JSONResponse:
            async with self.session_repo.session_maker() as session, session.begin():
                current_launcher = await self.session_repo.get_launcher(user, launcher_id)
                launcher_patch = validate_session_launcher_patch(body, current_launcher)
                launcher = await self.session_repo.update_launcher(
                    user=user, launcher_id=launcher_id, patch=launcher_patch, session=session
                )
            return validated_json(apispec.SessionLauncher, launcher)

        return "/session_launchers/<launcher_id:ulid>", ["PATCH"], _patch

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific session launcher."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete(_: Request, user: base_models.APIUser, launcher_id: ULID) -> HTTPResponse:
            await self.session_repo.delete_launcher(user=user, launcher_id=launcher_id)
            return HTTPResponse(status=204)

        return "/session_launchers/<launcher_id:ulid>", ["DELETE"], _delete

    def get_project_launchers(self) -> BlueprintFactoryResponse:
        """Get all launchers belonging to a project."""

        @authenticate(self.authenticator)
        async def _get_launcher(_: Request, user: base_models.APIUser, project_id: ULID) -> JSONResponse:
            launchers = await self.session_repo.get_project_launchers(user=user, project_id=project_id)
            return validated_json(apispec.SessionLaunchersList, launchers)

        return "/projects/<project_id:ulid>/session_launchers", ["GET"], _get_launcher


@dataclass(kw_only=True)
class SessionLauncherSecretBP(CustomBlueprint):
    """Handlers for manipulating session launcher secrets."""

    session_secret_repo: SessionSecretRepository
    authenticator: base_models.Authenticator

    def get_session_launcher_secret_slots(self) -> BlueprintFactoryResponse:
        """Get the secret slots of a session launcher."""

        @authenticate(self.authenticator)
        async def _get_session_launcher_secret_slots(
            _: Request, user: base_models.APIUser, launcher_id: ULID
        ) -> JSONResponse:
            secret_slots = await self.session_secret_repo.get_all_session_launcher_secret_slots_from_sesion_launcher(
                user=user, session_launcher_id=launcher_id
            )
            return validated_json(apispec.SessionSecretSlotList, secret_slots)

        return "/session_launchers/<launcher_id:ulid>/secret_slots", ["GET"], _get_session_launcher_secret_slots

    def post_session_launcher_secret_slot(self) -> BlueprintFactoryResponse:
        """Create a new secret slot on a session launcher."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.SessionSecretSlotPost)
        async def _post_session_launcher_secret_slot(
            _: Request, user: base_models.APIUser, body: apispec.SessionSecretSlotPost
        ) -> JSONResponse:
            unsaved_secret_slot = validate_unsaved_session_launcher_secret_slot(body)
            secret_slot = await self.session_secret_repo.insert_session_launcher_secret_slot(
                user=user, secret_slot=unsaved_secret_slot
            )
            return validated_json(apispec.SessionSecretSlot, secret_slot, status=201)

        return "/session_launcher_secret_slots", ["POST"], _post_session_launcher_secret_slot

    def get_session_launcher_secret_slot(self) -> BlueprintFactoryResponse:
        """Get the details of a secret slot."""

        @authenticate(self.authenticator)
        async def _get_session_launcher_secret_slot(
            _: Request, user: base_models.APIUser, slot_id: ULID
        ) -> JSONResponse:
            secret_slot = await self.session_secret_repo.get_session_launcher_secret_slot(user=user, slot_id=slot_id)
            return validated_json(apispec.SessionSecretSlot, secret_slot)

        return "/session_launcher_secret_slots/<slot_id:ulid>", ["GET"], _get_session_launcher_secret_slot

    def patch_session_launcher_secret_slot(self) -> BlueprintFactoryResponse:
        """Update specific fields of an existing secret slot."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.SessionSecretSlotPatch)
        async def _patch_session_launcher_secret_slot(
            _: Request, user: base_models.APIUser, slot_id: ULID, body: apispec.SessionSecretSlotPatch
        ) -> JSONResponse:
            secret_slot_patch = validate_session_launcher_secret_slot_patch(body)
            secret_slot = await self.session_secret_repo.update_session_launcher_secret_slot(
                user=user, slot_id=slot_id, patch=secret_slot_patch
            )
            return validated_json(apispec.SessionSecretSlot, secret_slot)

        return "/session_launcher_secret_slots/<slot_id:ulid>", ["PATCH"], _patch_session_launcher_secret_slot

    def delete_session_launcher_secret_slot(self) -> BlueprintFactoryResponse:
        """Remove a secret slot."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete_session_launcher_secret_slot(
            _: Request, user: base_models.APIUser, slot_id: ULID
        ) -> HTTPResponse:
            await self.session_secret_repo.delete_session_launcher_secret_slot(user=user, slot_id=slot_id)
            return HTTPResponse(status=204)

        return "/session_launcher_secret_slots/<slot_id:ulid>", ["DELETE"], _delete_session_launcher_secret_slot

    def get_session_launcher_secrets(self) -> BlueprintFactoryResponse:
        """Get the current user's secrets of a session launcher."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _get_session_launcher_secrets(
            _: Request, user: base_models.APIUser, launcher_id: ULID
        ) -> JSONResponse:
            secrets = await self.session_secret_repo.get_all_session_launcher_secrets_from_sesion_launcher(
                user=user, session_launcher_id=launcher_id
            )
            return validated_json(apispec.SessionSecretList, secrets)

        return "/session_launchers/<launcher_id:ulid>/secrets", ["GET"], _get_session_launcher_secrets

    def patch_session_launcher_secrets(self) -> BlueprintFactoryResponse:
        """Save user secrets for a session launcher."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate_body_root_model(json=apispec.SessionSecretPatchList)
        async def _patch_session_launcher_secrets(
            _: Request, user: base_models.APIUser, launcher_id: ULID, body: apispec.SessionSecretPatchList
        ) -> JSONResponse:
            secrets_patch = validate_session_launcher_secrets_patch(body)
            secrets = await self.session_secret_repo.patch_session_launcher_secrets(
                user=user, session_launcher_id=launcher_id, secrets=secrets_patch
            )
            return validated_json(apispec.SessionSecretList, secrets)

        return "/session_launchers/<launcher_id:ulid>/secrets", ["PATCH"], _patch_session_launcher_secrets

    def delete_session_launcher_secrets(self) -> BlueprintFactoryResponse:
        """Remove all user secrets for a session launcher."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete_session_launcher_secrets(
            _: Request, user: base_models.APIUser, launcher_id: ULID
        ) -> HTTPResponse:
            await self.session_secret_repo.delete_session_launcher_secrets(user=user, session_launcher_id=launcher_id)
            return HTTPResponse(status=204)

        return "/session_launchers/<launcher_id:ulid>/secrets", ["DELETE"], _delete_session_launcher_secrets
