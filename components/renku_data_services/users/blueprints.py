"""Blueprints for the user endpoints."""

from dataclasses import dataclass
from typing import Any

from sanic import HTTPResponse, Request, json
from sanic.response import JSONResponse
from sanic_ext import validate
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services.base_api.auth import authenticate, only_admins, only_authenticated, validate_path_user_id
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.misc import validate_query
from renku_data_services.base_models.validation import validated_json
from renku_data_services.errors import errors
from renku_data_services.secrets.db import UserSecretsRepo
from renku_data_services.secrets.models import Secret, SecretKind
from renku_data_services.users import apispec, models
from renku_data_services.users.core import validate_secret_patch, validate_unsaved_secret
from renku_data_services.users.db import UserPreferencesRepository, UserRepo


@dataclass(kw_only=True)
class KCUsersBP(CustomBlueprint):
    """Handlers for creating, listing, and deleting users."""

    repo: UserRepo
    authenticator: base_models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """Get all users or search by email."""

        @authenticate(self.authenticator)
        @validate_query(query=apispec.UserParams)
        async def _get_all(request: Request, user: base_models.APIUser, query: apispec.UserParams) -> JSONResponse:
            users = await self.repo.get_users(requested_by=user, email=query.exact_email)
            return validated_json(
                apispec.UsersWithId,
                [
                    dict(
                        id=user.id,
                        username=user.namespace.path.first.value,
                        email=user.email,
                        first_name=user.first_name,
                        last_name=user.last_name,
                    )
                    for user in users
                ],
            )

        return "/users", ["GET"], _get_all

    def get_self(self) -> BlueprintFactoryResponse:
        """Get info about the logged in user."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _get_self(_: Request, user: base_models.APIUser) -> JSONResponse:
            if not user.is_authenticated or user.id is None:
                raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")
            user_info = await self.repo.get_or_create_user(requested_by=user, id=user.id)
            if not user_info:
                raise errors.MissingResourceError(message=f"The user with ID {user.id} cannot be found.")
            return validated_json(
                apispec.SelfUserInfo,
                dict(
                    id=user_info.id,
                    username=user_info.namespace.path.first.value,
                    email=user_info.email,
                    first_name=user_info.first_name,
                    last_name=user_info.last_name,
                    is_admin=user.is_admin,
                ),
            )

        return "/user", ["GET"], _get_self

    def get_secret_key(self) -> BlueprintFactoryResponse:
        """Get the user's secret key.

        This is used to decrypt user secrets. This endpoint is only accessible from within the cluster.
        """

        @authenticate(self.authenticator)
        async def _get_secret_key(_: Request, user: base_models.APIUser) -> JSONResponse:
            secret_key = await self.repo.get_or_create_user_secret_key(requested_by=user)
            return json({"secret_key": secret_key})

        return "/user/secret_key", ["GET"], _get_secret_key

    def get_one(self) -> BlueprintFactoryResponse:
        """Get info about a specific user."""

        @authenticate(self.authenticator)
        async def _get_one(_: Request, user: base_models.APIUser, user_id: str) -> JSONResponse:
            user_info = await self.repo.get_or_create_user(requested_by=user, id=user_id)
            if not user_info:
                raise errors.MissingResourceError(message=f"The user with ID {user_id} cannot be found.")
            return validated_json(
                apispec.UserWithId,
                dict(
                    id=user_info.id,
                    username=user_info.namespace.path.first.value,
                    email=user_info.email,
                    first_name=user_info.first_name,
                    last_name=user_info.last_name,
                ),
            )

        return "/users/<user_id>", ["GET"], _get_one

    def delete_one(self) -> BlueprintFactoryResponse:
        """Delete a specific user by their Keycloak ID."""

        @authenticate(self.authenticator)
        @validate_path_user_id
        @only_admins
        async def _delete_one(_: Request, requested_by: base_models.APIUser, user_id: str) -> HTTPResponse:
            await self.repo.remove_user(requested_by=requested_by, user_id=user_id)
            return HTTPResponse(status=204)

        return "/users/<user_id>", ["DELETE"], _delete_one


@dataclass(kw_only=True)
class UserSecretsBP(CustomBlueprint):
    """Handlers for user secrets.

    Secrets storage is jointly handled by data service and secret service.
    Each user has their own secret key 'user_secret', encrypted at rest, that only data service can decrypt.
    Secret service has a public private key combo where only it knows the private key. To store a secret,
    it is first encrypted with the user_secret, and then with a random password that is passed to the secret service by
    encrypting it with the secret service's public key and then storing both in the database. This way neither the data
    service nor the secret service can decrypt the secrets on their own.
    """

    secret_repo: UserSecretsRepo
    authenticator: base_models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """Get all user's secrets."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate_query(query=apispec.UserSecretsParams)
        async def _get_all(
            request: Request, user: base_models.APIUser, query: apispec.UserSecretsParams
        ) -> JSONResponse:
            secret_kind = SecretKind[query.kind.value]
            secrets = await self.secret_repo.get_user_secrets(requested_by=user, kind=secret_kind)
            return validated_json(
                apispec.SecretsList,
                [self._dump_secret(s) for s in secrets],
                exclude_none=False,
            )

        return "/user/secrets", ["GET"], _get_all

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a user secret."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _get_one(_: Request, user: base_models.APIUser, secret_id: ULID) -> JSONResponse:
            secret = await self.secret_repo.get_secret_by_id(requested_by=user, secret_id=secret_id)
            return validated_json(
                apispec.SecretWithId,
                self._dump_secret(secret),
                exclude_none=False,
            )

        return "/user/secrets/<secret_id:ulid>", ["GET"], _get_one

    def post(self) -> BlueprintFactoryResponse:
        """Create a new secret."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.SecretPost)
        async def _post(_: Request, user: base_models.APIUser, body: apispec.SecretPost) -> JSONResponse:
            new_secret = validate_unsaved_secret(body)
            inserted_secret = await self.secret_repo.insert_secret(requested_by=user, secret=new_secret)
            return validated_json(
                apispec.SecretWithId, self._dump_secret(inserted_secret), exclude_none=False, status=201
            )

        return "/user/secrets", ["POST"], _post

    def patch(self) -> BlueprintFactoryResponse:
        """Update a specific secret."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.SecretPatch)
        async def _patch(
            _: Request, user: base_models.APIUser, secret_id: ULID, body: apispec.SecretPatch
        ) -> JSONResponse:
            secret_patch = validate_secret_patch(body)
            updated_secret = await self.secret_repo.update_secret(
                requested_by=user, secret_id=secret_id, patch=secret_patch
            )
            return validated_json(
                apispec.SecretWithId,
                self._dump_secret(updated_secret),
                exclude_none=False,
            )

        return "/user/secrets/<secret_id:ulid>", ["PATCH"], _patch

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific secret."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete(_: Request, user: base_models.APIUser, secret_id: ULID) -> HTTPResponse:
            await self.secret_repo.delete_secret(requested_by=user, secret_id=secret_id)
            return HTTPResponse(status=204)

        return "/user/secrets/<secret_id:ulid>", ["DELETE"], _delete

    @staticmethod
    def _dump_secret(secret: Secret) -> dict[str, Any]:
        """Dumps a secret for API responses."""
        return dict(
            id=str(secret.id),
            name=secret.name,
            default_filename=secret.default_filename,
            kind=secret.kind.value,
            modification_date=secret.modification_date,
            expiration_timestamp=secret.expiration_timestamp,
            session_secret_slot_ids=[str(item) for item in secret.session_secret_slot_ids],
            data_connector_ids=[str(item) for item in secret.data_connector_ids],
        )


@dataclass(kw_only=True)
class UserPreferencesBP(CustomBlueprint):
    """Handlers for manipulating user preferences."""

    user_preferences_repo: UserPreferencesRepository
    authenticator: base_models.Authenticator

    def get(self) -> BlueprintFactoryResponse:
        """Get user preferences for the logged in user."""

        @authenticate(self.authenticator)
        async def _get(_: Request, user: base_models.APIUser) -> JSONResponse:
            user_preferences: models.UserPreferences
            user_preferences = await self.user_preferences_repo.get_user_preferences(requested_by=user)
            return validated_json(apispec.UserPreferences, user_preferences)

        return "/user/preferences", ["GET"], _get

    def post_pinned_projects(self) -> BlueprintFactoryResponse:
        """Add a pinned project to user preferences for the logged in user."""

        @authenticate(self.authenticator)
        @validate(json=apispec.AddPinnedProject)
        async def _post(_: Request, user: base_models.APIUser, body: apispec.AddPinnedProject) -> JSONResponse:
            res = await self.user_preferences_repo.add_pinned_project(requested_by=user, project_slug=body.project_slug)
            return validated_json(apispec.UserPreferences, res)

        return "/user/preferences/pinned_projects", ["POST"], _post

    def delete_pinned_projects(self) -> BlueprintFactoryResponse:
        """Remove a pinned project from user preferences for the logged in user."""

        @authenticate(self.authenticator)
        @validate_query(query=apispec.DeletePinnedParams)
        async def _delete(
            request: Request, user: base_models.APIUser, query: apispec.DeletePinnedParams
        ) -> JSONResponse:
            res = await self.user_preferences_repo.remove_pinned_project(
                requested_by=user, project_slug=query.project_slug
            )
            return validated_json(apispec.UserPreferences, res)

        return "/user/preferences/pinned_projects", ["DELETE"], _delete

    def post_dismiss_project_migration_banner(self) -> BlueprintFactoryResponse:
        """Add dismiss project migration banner to user preferences for the logged in user."""

        @authenticate(self.authenticator)
        async def _post(_: Request, user: base_models.APIUser) -> JSONResponse:
            res = await self.user_preferences_repo.add_dismiss_project_migration_banner(requested_by=user)
            return validated_json(apispec.UserPreferences, res)

        return "/user/preferences/dismiss_project_migration_banner", ["POST"], _post

    def delete_dismiss_project_migration_banner(self) -> BlueprintFactoryResponse:
        """Remove dismiss project migration banner from user preferences for the logged in user."""

        @authenticate(self.authenticator)
        async def _delete(request: Request, user: base_models.APIUser) -> JSONResponse:
            res = await self.user_preferences_repo.remove_dismiss_project_migration_banner(requested_by=user)
            return validated_json(apispec.UserPreferences, res)

        return "/user/preferences/dismiss_project_migration_banner", ["DELETE"], _delete
