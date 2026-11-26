"""Cloud storage app."""

from collections.abc import Callable
from dataclasses import dataclass

from sanic import Request, empty
from sanic.response import HTTPResponse, JSONResponse
from sanic_ext import validate
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.base_api.auth import (
    authenticate,
    only_authenticated,
)
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.etag import if_match_required
from renku_data_services.base_api.misc import validate_query
from renku_data_services.base_models.validation import validated_json
from renku_data_services.notebooks.api.classes.k8s_client import NotebookK8sClient
from renku_data_services.notebooks.data_sources import DataSourceRepository
from renku_data_services.storage import apispec
from renku_data_services.storage.core import (
    validate_project_storage_v2_admin_patch,
    validate_project_storage_v2_patch,
    validate_unsaved_project_storage_v2,
)
from renku_data_services.storage.db import ProjectStorageV2Repository
from renku_data_services.storage.rclone import RCloneValidator


@dataclass(kw_only=True)
class StorageSchemaBP(CustomBlueprint):
    """Handler for getting RClone storage schema."""

    data_source_repo: DataSourceRepository
    authenticator: base_models.Authenticator

    def get(self) -> BlueprintFactoryResponse:
        """Get cloud storage for a repository."""

        async def _get(_: Request, validator: RCloneValidator) -> JSONResponse:
            return validated_json(apispec.RCloneSchema, validator.asdict())

        return "/storage_schema", ["GET"], _get

    def test_connection(self) -> BlueprintFactoryResponse:
        """Validate an RClone config."""

        @authenticate(self.authenticator)
        @validate(json=apispec.StorageSchemaTestConnectionPostRequest)
        async def _test_connection(
            request: Request,
            user: base_models.APIUser,
            validator: RCloneValidator,
            body: apispec.StorageSchemaTestConnectionPostRequest,
        ) -> HTTPResponse:
            validator.validate(body.configuration, keep_sensitive=True)
            result = await validator.test_connection(
                body.configuration, body.source_path, user=user, data_source_repo=self.data_source_repo
            )
            if not result.success:
                raise errors.ValidationError(message=result.error)
            return empty(204)

        return "/storage_schema/test_connection", ["POST"], _test_connection

    def validate(self) -> BlueprintFactoryResponse:
        """Validate an RClone config."""

        @validate(json=apispec.RCloneConfigValidate)
        async def _validate(
            request: Request, validator: RCloneValidator, body: apispec.RCloneConfigValidate
        ) -> HTTPResponse:
            if body.root is None:
                raise errors.ValidationError(message="The request body is empty. Please provide a valid JSON object.")
            validator.validate(body.root, keep_sensitive=True)
            return empty(204)

        return "/storage_schema/validate", ["POST"], _validate

    def obscure(self) -> BlueprintFactoryResponse:
        """Obscure values in config."""

        @validate(json=apispec.StorageSchemaObscurePostRequest)
        async def _obscure(
            request: Request, validator: RCloneValidator, body: apispec.StorageSchemaObscurePostRequest
        ) -> JSONResponse:
            config = await validator.obscure_config(body.configuration)
            return validated_json(apispec.RCloneConfigValidate, config)

        return "/storage_schema/obscure", ["POST"], _obscure


@dataclass(kw_only=True)
class ProjectStorageV2BP(CustomBlueprint):
    """Handlers for project storages v2."""

    k8s_client: NotebookK8sClient
    project_storage_v2_repo: ProjectStorageV2Repository
    authenticator: base_models.Authenticator
    session_maker: Callable[..., AsyncSession]

    def get_all(self) -> BlueprintFactoryResponse:
        """Get all visible project storages.

        The list of storages can be filtered using the query parameters.
        """

        @authenticate(self.authenticator)
        @validate_query(query=apispec.ProjectStoragesGetQuery)
        async def _get_all(
            _: Request, user: base_models.APIUser, query: apispec.ProjectStoragesGetQuery
        ) -> JSONResponse:
            project_id = ULID.from_str(query.project_id) if query.project_id else None
            storage_quota_id = ULID.from_str(query.storage_quota_id) if query.storage_quota_id else None
            async with self.session_maker() as session, session.begin():
                storages = self.project_storage_v2_repo.get_all_project_storages(
                    session=session,
                    user=user,
                    project_id=project_id,
                    storage_quota_id=storage_quota_id,
                )
                result = [item async for item in storages]
            return validated_json(apispec.ProjectStorages, result)

        return "/storages", ["GET"], _get_all

    def post(self) -> BlueprintFactoryResponse:
        """Create a project storage."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.ProjectStoragePost)
        async def _post(_: Request, user: base_models.APIUser, body: apispec.ProjectStoragePost) -> JSONResponse:
            new_storage = validate_unsaved_project_storage_v2(body=body)
            async with self.session_maker() as session, session.begin():
                storage = await self.project_storage_v2_repo.insert_project_storage(
                    session=session, user=user, project_storage=new_storage
                )
            return validated_json(apispec.ProjectStorage, storage, status=201)

        return "/storages", ["POST"], _post

    def patch(self) -> BlueprintFactoryResponse:
        """Update a project storage."""

        @authenticate(self.authenticator)
        @only_authenticated
        @if_match_required
        @validate(json=apispec.ProjectStoragePatch)
        async def _patch(
            _: Request,
            user: base_models.APIUser,
            storage_id: ULID,
            body: apispec.ProjectStoragePatch,
            etag: str,
        ) -> HTTPResponse:
            patch = validate_project_storage_v2_patch(body=body)
            async with self.session_maker() as session, session.begin():
                storage = await self.project_storage_v2_repo.update_project_storage(
                    k8s_client=self.k8s_client,
                    session=session,
                    user=user,
                    storage_id=storage_id,
                    patch=patch,
                    etag=etag,
                )
            return validated_json(apispec.ProjectStorage, storage)

        return "/storages/<storage_id:ulid>", ["PATCH"], _patch

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a project storage."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete(
            _: Request,
            user: base_models.APIUser,
            storage_id: ULID,
        ) -> HTTPResponse:
            async with self.session_maker() as session, session.begin():
                await self.project_storage_v2_repo.delete_project_storage(
                    k8s_client=self.k8s_client, session=session, user=user, storage_id=storage_id
                )
            return HTTPResponse(status=204)

        return "/storages/<storage_id:ulid>", ["DELETE"], _delete

    def admin_patch(self) -> BlueprintFactoryResponse:
        """Update a project storage with an unsafe operation."""

        @authenticate(self.authenticator)
        @only_authenticated
        @if_match_required
        @validate(json=apispec.ProjectStorageAdminPatchV2)
        async def _admin_patch(
            _: Request,
            user: base_models.APIUser,
            storage_id: ULID,
            body: apispec.ProjectStorageAdminPatchV2,
            etag: str,
        ) -> HTTPResponse:
            _patch = validate_project_storage_v2_admin_patch(body=body)
            # async with self.session_maker() as session, session.begin():
            #     storage = await self.project_storage_v2_repo.update_project_storage(
            #         k8s_client=self.k8s_client,
            #         session=session,
            #         user=user,
            #         storage_id=storage_id,
            #         patch=patch,
            #         etag=etag,
            #     )
            # return validated_json(apispec.ProjectStorageV2, storage)
            raise NotImplementedError()

        return "/storages/<storage_id:ulid>/admin", ["PATCH"], _admin_patch
