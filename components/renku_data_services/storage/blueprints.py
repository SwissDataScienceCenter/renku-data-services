"""Cloud storage app."""

from dataclasses import dataclass
from typing import Any

from sanic import Request, empty
from sanic.response import HTTPResponse, JSONResponse
from sanic_ext import validate
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.base_api.auth import (
    authenticate,
    only_admins,
    only_authenticated,
)
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.etag import extract_if_none_match, if_match_required
from renku_data_services.base_api.misc import validate_query
from renku_data_services.base_api.pagination import PaginationRequest, paginate
from renku_data_services.base_models.validation import validate_and_dump, validated_json
from renku_data_services.notebooks.data_sources import DataSourceRepository
from renku_data_services.storage import apispec, models
from renku_data_services.storage.core import (
    validate_project_storage_allow_patch,
    validate_project_storage_allow_post,
    validate_project_storage_patch,
    validate_unsaved_project_storage,
)
from renku_data_services.storage.db import ProjectStorageRepository
from renku_data_services.storage.project_storage_k8s import ProjectStorageK8s
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
class ProjectStorageBP(CustomBlueprint):
    """Handler for project storage."""

    project_storage_k8s: ProjectStorageK8s
    project_storage_repo: ProjectStorageRepository
    authenticator: base_models.Authenticator

    def get_one_storage(self) -> BlueprintFactoryResponse:
        """Get a specific project storage connector."""

        @authenticate(self.authenticator)
        @extract_if_none_match
        async def _get_one(_: Request, user: base_models.APIUser, storage_id: ULID, etag: str | None) -> HTTPResponse:
            project_storage = await self.project_storage_repo.get_project_storage(user=user, storage_id=storage_id)
            if project_storage is None:
                raise errors.MissingResourceError(message=f"No project storage found for storage: {storage_id}")

            if project_storage.etag == etag:
                return HTTPResponse(status=304)

            headers = {"ETag": project_storage.etag}
            return validated_json(
                apispec.ProjectStorage,
                self._dump_project_storage(project_storage),
                headers=headers,
            )

        return "/storage/<storage_id:ulid>", ["GET"], _get_one

    def get_storage_to_project(self) -> BlueprintFactoryResponse:
        """List all project storage to a given project."""

        @authenticate(self.authenticator)
        async def _get_all_storage_to_project(
            _: Request,
            user: base_models.APIUser,
            project_id: ULID,
        ) -> JSONResponse:
            project_storage = await self.project_storage_repo.get_storage_to(user=user, project_id=project_id)
            result = [self._dump_project_storage(project_storage)] if project_storage else []
            return validated_json(apispec.ProjectStorageList, result)

        return "/projects/<project_id:ulid>/storage", ["GET"], _get_all_storage_to_project

    def get_storage_config(self) -> BlueprintFactoryResponse:
        """Get the current config used for project storage."""

        @authenticate(self.authenticator)
        @only_admins
        async def _get_project_config(_: Request, user: base_models.APIUser) -> JSONResponse:
            storage_config = self.project_storage_repo.get_project_storage_config()
            result = apispec.ProjectStorageConfig(
                enabled=storage_config.enabled, max_size=int(storage_config.maximum_size.to_gibi())
            )
            return validated_json(apispec.ProjectStorageConfig, result)

        return "/storage/config", ["GET"], _get_project_config

    def delete_storage(self) -> BlueprintFactoryResponse:
        """Delete a specific project storage."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete_storage(
            _: Request,
            user: base_models.APIUser,
            storage_id: ULID,
        ) -> HTTPResponse:
            deleted = await self.project_storage_repo.delete_project_storage(user=user, storage_id=storage_id)
            if deleted:
                await self.project_storage_k8s.delete_volume(deleted)
            return HTTPResponse(status=204)

        return "/storage/<storage_id:ulid>", ["DELETE"], _delete_storage

    def post_storage(self) -> BlueprintFactoryResponse:
        """Create a new shared project storage."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.ProjectStoragePost)
        async def _post_storage(
            _: Request, user: base_models.APIUser, body: apispec.ProjectStoragePost
        ) -> JSONResponse:
            dc = validate_unsaved_project_storage(body)
            result = await self.project_storage_repo.insert_project_storage(user, dc)
            headers = {"ETag": result.etag}
            return validated_json(
                apispec.ProjectStorage, self._dump_project_storage(result), headers=headers, status=201
            )

        return "/storage", ["POST"], _post_storage

    def patch_storage(self) -> BlueprintFactoryResponse:
        """Partially update a project storage entry."""

        @authenticate(self.authenticator)
        @only_authenticated
        @if_match_required
        @validate(json=apispec.ProjectStoragePatch)
        async def _patch_storage(
            _: Request,
            user: base_models.APIUser,
            storage_id: ULID,
            body: apispec.ProjectStoragePatch,
            etag: str,
        ) -> JSONResponse:
            existing_storage = await self.project_storage_repo.get_project_storage(user=user, storage_id=storage_id)
            if existing_storage is None:
                raise errors.MissingResourceError(message=f"No project storage found for storage: {storage_id}")

            storage_patch = validate_project_storage_patch(existing_storage, body)
            updated_storage = await self.project_storage_repo.update_project_storage(
                user=user, storage_id=storage_id, patch=storage_patch, etag=etag
            )
            headers = {"ETag": updated_storage.etag}
            return validated_json(
                apispec.ProjectStorage,
                self._dump_project_storage(updated_storage),
                headers=headers,
            )

        return "/storage/<storage_id:ulid>", ["PATCH"], _patch_storage

    def get_all_storage_allows(self) -> BlueprintFactoryResponse:
        """List all projects in the storage allow list."""

        @authenticate(self.authenticator)
        @only_admins
        @validate_query(query=apispec.ProjectStorageAllowListQuery)
        @paginate
        async def _get_all_storage_allows(
            _: Request,
            user: base_models.APIUser,
            pagination: PaginationRequest,
            query: apispec.ProjectStorageAllowListQuery,
        ) -> tuple[list[dict[str, Any]], int]:
            project_name = query.project_name if query.project_name else None
            allows, total = await self.project_storage_repo.get_project_storage_allows(
                user, pagination, project_name=project_name
            )
            return [
                validate_and_dump(
                    apispec.ProjectStorageAllow,
                    self._dump_project_storage_allow_detail(a),
                )
                for a in allows
            ], total

        return "/storage/allow", ["GET"], _get_all_storage_allows

    def post_storage_allow(self) -> BlueprintFactoryResponse:
        """Add a project to the storage allow list."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.ProjectStorageAllowPost)
        async def _post_storage_allow(
            _: Request, user: base_models.APIUser, body: apispec.ProjectStorageAllowPost
        ) -> JSONResponse:
            allow = validate_project_storage_allow_post(body)
            inserted = await self.project_storage_repo.insert_project_storage_allow(user, allow)
            return validated_json(
                apispec.ProjectStorageAllowPost,
                self._dump_project_storage_allow_post(inserted),
                status=201,
            )

        return "/storage/allow", ["POST"], _post_storage_allow

    def patch_storage_allow(self) -> BlueprintFactoryResponse:
        """Partially update a project storage allow entry."""

        @authenticate(self.authenticator)
        @only_admins
        @if_match_required
        @validate(json=apispec.ProjectStorageAllowPatch)
        async def _patch(
            _: Request,
            user: base_models.APIUser,
            project_id: ULID,
            body: apispec.ProjectStorageAllowPatch,
            etag: str,
        ) -> JSONResponse:
            existing_entry = await self.project_storage_repo.get_project_storage_allow(user=user, project_id=project_id)
            if not existing_entry:
                raise errors.MissingResourceError(message=f"No project storage allow entry for project {project_id}")

            pse_patch = validate_project_storage_allow_patch(existing_entry, body)
            pse_update = await self.project_storage_repo.update_project_storage_allow(
                user=user, project_id=project_id, patch=pse_patch, etag=etag
            )

            headers = {"ETag": pse_update.new.etag}
            return validated_json(
                apispec.ProjectStorageAllow, self._dump_project_storage_allow_detail(pse_update.new), headers=headers
            )

        return "/storage/allow/<project_id:ulid>", ["PATCH"], _patch

    def get_storage_allow(self) -> BlueprintFactoryResponse:
        """Get the storage allow entry for a project."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _get_storage_allow(_: Request, user: base_models.APIUser, project_id: ULID) -> HTTPResponse:
            allow = await self.project_storage_repo.get_project_storage_allow(user, project_id)
            if allow is None:
                raise errors.MissingResourceError(message=f"Project {project_id} is not in the storage allow list.")

            headers = {"ETag": allow.etag}
            return validated_json(
                apispec.ProjectStorageAllow, self._dump_project_storage_allow_detail(allow), headers=headers
            )

        return "/storage/allow/<project_id:ulid>", ["GET"], _get_storage_allow

    def delete_storage_allow(self) -> BlueprintFactoryResponse:
        """Remove a project from the storage allow list."""

        @authenticate(self.authenticator)
        @only_admins
        async def _delete_storage_allow(_: Request, user: base_models.APIUser, project_id: ULID) -> HTTPResponse:
            deleted = await self.project_storage_repo.delete_project_storage_allow(user, project_id)
            if deleted:
                await self.project_storage_k8s.delete_volume(deleted)
            return HTTPResponse(status=204)

        return "/storage/allow/<project_id:ulid>", ["DELETE"], _delete_storage_allow

    @staticmethod
    def _dump_project_storage(ps: models.ProjectStorage) -> apispec.ProjectStorage:
        return apispec.ProjectStorage(
            id=str(ps.id),
            project_id=str(ps.project_id),
            size=int(ps.size.to_gibi()),
            mount_path=ps.mount_path.as_posix(),
            created_by=ps.created_by,
            creation_date=ps.creation_date,
            updated_at=ps.updated_at,
            etag=ps.etag,
        )

    @staticmethod
    def _dump_project_storage_allow_detail(ps: models.ProjectStorageAllowDetail) -> apispec.ProjectStorageAllow:
        return apispec.ProjectStorageAllow(
            project_id=str(ps.project_id),
            max_size=int(ps.max_size.to_gibi()),
            name=ps.name,
            namespace=ps.namespace_path.serialize(),
            etag=ps.etag,
        )

    @staticmethod
    def _dump_project_storage_allow_post(ps: models.ProjectStorageAllow) -> apispec.ProjectStorageAllowPost:
        pref: apispec.ProjectIdRef | apispec.ProjectSlugRef
        match ps.project_ref.ref:
            case ULID() as id:
                pref = apispec.ProjectIdRef(id=str(id))
            case base_models.ProjectPath() as p:
                pref = apispec.ProjectSlugRef(slug=p.serialize())

        return apispec.ProjectStorageAllowPost(
            project_ref=pref,
            max_size=int(ps.max_size.to_gibi()),
        )
