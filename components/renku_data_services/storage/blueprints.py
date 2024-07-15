"""Cloud storage app."""

from dataclasses import dataclass
from typing import Any

from sanic import HTTPResponse, Request, empty, json
from sanic.response import JSONResponse
from sanic_ext import validate
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.base_api.auth import authenticate
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.storage import apispec, models
from renku_data_services.storage.apispec_base import RepositoryFilter, RepositoryFilterV2
from renku_data_services.storage.db import StorageRepository, StorageV2Repository
from renku_data_services.storage.rclone import RCloneValidator


def dump_storage_with_sensitive_fields(storage: models.CloudStorage, validator: RCloneValidator) -> dict[str, Any]:
    """Dump a CloudStorage model alongside sensitive fields."""
    return apispec.CloudStorageGet.model_validate(
        {
            "storage": apispec.CloudStorageWithId.model_validate(storage).model_dump(exclude_none=True),
            "sensitive_fields": validator.get_private_fields(storage.configuration),
        }
    ).model_dump(exclude_none=True)


@dataclass(kw_only=True)
class StorageBP(CustomBlueprint):
    """Handlers for manipulating storage definitions."""

    storage_repo: StorageRepository
    authenticator: base_models.Authenticator

    def get(self) -> BlueprintFactoryResponse:
        """Get cloud storage for a repository."""

        @authenticate(self.authenticator)
        async def _get(request: Request, user: base_models.APIUser, validator: RCloneValidator) -> JSONResponse:
            res_filter = RepositoryFilter.model_validate(dict(request.query_args))
            storage: list[models.CloudStorage]
            storage = await self.storage_repo.get_storage(user=user, **res_filter.model_dump())

            return json([dump_storage_with_sensitive_fields(s, validator) for s in storage])

        return "/storage", ["GET"], _get

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a single storage by id."""

        @authenticate(self.authenticator)
        async def _get_one(
            request: Request,
            user: base_models.APIUser,
            storage_id: ULID,
            validator: RCloneValidator,
        ) -> JSONResponse:
            storage = await self.storage_repo.get_storage_by_id(storage_id, user=user)

            return json(dump_storage_with_sensitive_fields(storage, validator))

        return "/storage/<storage_id:ulid>", ["GET"], _get_one

    def post(self) -> BlueprintFactoryResponse:
        """Create a new cloud storage entry."""

        @authenticate(self.authenticator)
        async def _post(request: Request, user: base_models.APIUser, validator: RCloneValidator) -> JSONResponse:
            storage: models.CloudStorage
            if not isinstance(request.json, dict):
                body_type = type(request.json)
                raise errors.ValidationError(
                    message=f"The payload is supposed to be a dictionary, got {body_type.__name__}"
                )
            if "storage_url" in request.json:
                url_body = apispec.CloudStorageUrl(**request.json)
                storage = models.CloudStorage.from_url(
                    storage_url=url_body.storage_url,
                    project_id=url_body.project_id.root,
                    name=url_body.name,
                    target_path=url_body.target_path,
                    readonly=url_body.readonly,
                )
            else:
                body = apispec.CloudStorage(**request.json)
                storage = models.CloudStorage.from_dict(body.model_dump())

            validator.validate(storage.configuration.model_dump())

            res = await self.storage_repo.insert_storage(storage=storage, user=user)
            return json(dump_storage_with_sensitive_fields(res, validator), 201)

        return "/storage", ["POST"], _post

    def put(self) -> BlueprintFactoryResponse:
        """Replace a storage entry."""

        @authenticate(self.authenticator)
        async def _put(
            request: Request,
            user: base_models.APIUser,
            storage_id: ULID,
            validator: RCloneValidator,
        ) -> JSONResponse:
            if not request.json:
                raise errors.ValidationError(message="The request body is empty. Please provide a valid JSON object.")
            if not isinstance(request.json, dict):
                raise errors.ValidationError(message="The request body is not a valid JSON object.")
            if "storage_url" in request.json:
                url_body = apispec.CloudStorageUrl(**request.json)
                new_storage = models.CloudStorage.from_url(
                    storage_url=url_body.storage_url,
                    project_id=url_body.project_id.root,
                    name=url_body.name,
                    target_path=url_body.target_path,
                    readonly=url_body.readonly,
                )
            else:
                body = apispec.CloudStorage(**request.json)
                new_storage = models.CloudStorage.from_dict(body.model_dump())

            validator.validate(new_storage.configuration.model_dump())
            body_dict = new_storage.model_dump()
            del body_dict["storage_id"]
            res = await self.storage_repo.update_storage(storage_id=storage_id, user=user, **body_dict)
            return json(dump_storage_with_sensitive_fields(res, validator))

        return "/storage/<storage_id:ulid>", ["PUT"], _put

    def patch(self) -> BlueprintFactoryResponse:
        """Update parts of a storage entry."""

        @authenticate(self.authenticator)
        @validate(json=apispec.CloudStoragePatch)
        async def _patch(
            request: Request,
            user: base_models.APIUser,
            storage_id: ULID,
            body: apispec.CloudStoragePatch,
            validator: RCloneValidator,
        ) -> JSONResponse:
            existing_storage = await self.storage_repo.get_storage_by_id(storage_id, user=user)
            if body.configuration is not None:
                # we need to apply the patch to the existing storage to properly validate it
                body.configuration = {**existing_storage.configuration, **body.configuration}

                for k, v in list(body.configuration.items()):
                    if v is None:
                        # delete fields that were unset
                        del body.configuration[k]
                validator.validate(body.configuration)

            body_dict = body.model_dump(exclude_none=True)

            res = await self.storage_repo.update_storage(storage_id=storage_id, user=user, **body_dict)
            return json(dump_storage_with_sensitive_fields(res, validator))

        return "/storage/<storage_id:ulid>", ["PATCH"], _patch

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a storage entry."""

        @authenticate(self.authenticator)
        async def _delete(request: Request, user: base_models.APIUser, storage_id: ULID) -> HTTPResponse:
            await self.storage_repo.delete_storage(storage_id=storage_id, user=user)
            return empty(204)

        return "/storage/<storage_id:ulid>", ["DELETE"], _delete


@dataclass(kw_only=True)
class StoragesV2BP(CustomBlueprint):
    """Handlers for manipulating storage definitions."""

    storage_v2_repo: StorageV2Repository
    authenticator: base_models.Authenticator

    def get(self) -> BlueprintFactoryResponse:
        """Get cloud storage for a repository."""

        @authenticate(self.authenticator)
        async def _get(request: Request, user: base_models.APIUser, validator: RCloneValidator) -> JSONResponse:
            res_filter = RepositoryFilterV2.model_validate(dict(request.query_args))
            storage: list[models.CloudStorage]
            storage = await self.storage_v2_repo.get_storage(user=user, **res_filter.model_dump())

            return json([dump_storage_with_sensitive_fields(s, validator) for s in storage])

        return "/storages_v2", ["GET"], _get

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a single storage by id."""

        @authenticate(self.authenticator)
        async def _get_one(
            request: Request,
            user: base_models.APIUser,
            storage_id: ULID,
            validator: RCloneValidator,
        ) -> JSONResponse:
            storage = await self.storage_v2_repo.get_storage_by_id(storage_id, user=user)

            return json(dump_storage_with_sensitive_fields(storage, validator))

        return "/storages_v2/<storage_id:ulid>", ["GET"], _get_one

    def post(self) -> BlueprintFactoryResponse:
        """Create a new cloud storage entry."""

        @authenticate(self.authenticator)
        async def _post(request: Request, user: base_models.APIUser, validator: RCloneValidator) -> JSONResponse:
            storage: models.CloudStorage
            if not isinstance(request.json, dict):
                body_type = type(request.json)
                raise errors.ValidationError(
                    message=f"The payload is supposed to be a dictionary, got {body_type.__name__}"
                )
            if "storage_url" in request.json:
                url_body = apispec.CloudStorageUrl(**request.json)
                storage = models.CloudStorage.from_url(
                    storage_url=url_body.storage_url,
                    project_id=url_body.project_id.root,
                    name=url_body.name,
                    target_path=url_body.target_path,
                    readonly=url_body.readonly,
                )
            else:
                body = apispec.CloudStorage(**request.json)
                storage = models.CloudStorage.from_dict(body.model_dump())

            validator.validate(storage.configuration.model_dump())

            res = await self.storage_v2_repo.insert_storage(storage=storage, user=user)
            return json(dump_storage_with_sensitive_fields(res, validator), 201)

        return "/storages_v2", ["POST"], _post

    def patch(self) -> BlueprintFactoryResponse:
        """Update parts of a storage entry."""

        @authenticate(self.authenticator)
        @validate(json=apispec.CloudStoragePatch)
        async def _patch(
            request: Request,
            user: base_models.APIUser,
            storage_id: ULID,
            body: apispec.CloudStoragePatch,
            validator: RCloneValidator,
        ) -> JSONResponse:
            existing_storage = await self.storage_v2_repo.get_storage_by_id(storage_id, user=user)
            if body.configuration is not None:
                # we need to apply the patch to the existing storage to properly validate it
                body.configuration = {**existing_storage.configuration, **body.configuration}

                for k, v in list(body.configuration.items()):
                    if v is None:
                        # delete fields that were unset
                        del body.configuration[k]
                validator.validate(body.configuration)

            body_dict = body.model_dump(exclude_none=True)

            res = await self.storage_v2_repo.update_storage(storage_id=storage_id, user=user, **body_dict)
            return json(dump_storage_with_sensitive_fields(res, validator))

        return "/storages_v2/<storage_id:ulid>", ["PATCH"], _patch

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a storage entry."""

        @authenticate(self.authenticator)
        async def _delete(request: Request, user: base_models.APIUser, storage_id: ULID) -> HTTPResponse:
            await self.storage_v2_repo.delete_storage(storage_id=storage_id, user=user)
            return empty(204)

        return "/storages_v2/<storage_id:ulid>", ["DELETE"], _delete

    def upsert_secrets(self) -> BlueprintFactoryResponse:
        """Create/update secrets for a cloud storage."""

        @authenticate(self.authenticator)
        async def _upsert_secrets(request: Request, user: base_models.APIUser, storage_id: ULID) -> JSONResponse:
            body = apispec.CloudStorageSecretPostList.model_validate(request.json)
            result = await self.storage_v2_repo.upsert_storage_secrets(
                storage_id=storage_id, user=user, secrets=body.root
            )
            return json(
                apispec.CloudStorageSecretGetList.model_validate(result).model_dump(exclude_none=True, mode="json"), 201
            )

        return "/storages_v2/<storage_id:ulid>/secrets", ["POST"], _upsert_secrets

    def get_secrets(self) -> BlueprintFactoryResponse:
        """Return all secrets for a cloud storage."""

        @authenticate(self.authenticator)
        async def _get_secrets(request: Request, user: base_models.APIUser, storage_id: ULID) -> JSONResponse:
            result = await self.storage_v2_repo.get_storage_secrets(storage_id=storage_id, user=user)
            return json(
                apispec.CloudStorageSecretGetList.model_validate(result).model_dump(exclude_none=True, mode="json"), 200
            )

        return "/storages_v2/<storage_id:ulid>/secrets", ["GET"], _get_secrets

    def delete_secrets(self) -> BlueprintFactoryResponse:
        """Delete all secrets for a cloud storage."""

        @authenticate(self.authenticator)
        async def _delete_secrets(request: Request, user: base_models.APIUser, storage_id: ULID) -> HTTPResponse:
            await self.storage_v2_repo.delete_storage_secrets(storage_id=storage_id, user=user)
            return HTTPResponse(status=204)

        return "/storages_v2/<storage_id:ulid>/secrets", ["DELETE"], _delete_secrets


@dataclass(kw_only=True)
class StorageSchemaBP(CustomBlueprint):
    """Handler for getting RClone storage schema."""

    def get(self) -> BlueprintFactoryResponse:
        """Get cloud storage for a repository."""

        async def _get(_: Request, validator: RCloneValidator) -> JSONResponse:
            return json(validator.asdict())

        return "/storage_schema", ["GET"], _get

    def test_connection(self) -> BlueprintFactoryResponse:
        """Validate an RClone config."""

        async def _test_connection(request: Request, validator: RCloneValidator) -> HTTPResponse:
            if not request.json:
                raise errors.ValidationError(message="The request body is empty. Please provide a valid JSON object.")
            if not isinstance(request.json, dict):
                raise errors.ValidationError(message="The request body is not a valid JSON object.")
            if not request.json.get("configuration"):
                raise errors.ValidationError(message="No 'configuration' sent.")
            if not isinstance(request.json.get("configuration"), dict):
                config_type = type(request.json.get("configuration"))
                raise errors.ValidationError(
                    message=f"The R clone configuration should be a dictionary, not {config_type.__name__}"
                )
            if not request.json.get("source_path"):
                raise errors.ValidationError(message="'source_path' is required to test the connection.")
            validator.validate(request.json["configuration"], keep_sensitive=True)
            result = await validator.test_connection(request.json["configuration"], request.json["source_path"])
            if not result.success:
                raise errors.ValidationError(message=result.error)
            return empty(204)

        return "/storage_schema/test_connection", ["POST"], _test_connection

    def validate(self) -> BlueprintFactoryResponse:
        """Validate an RClone config."""

        async def _validate(request: Request, validator: RCloneValidator) -> HTTPResponse:
            if not request.json:
                raise errors.ValidationError(message="The request body is empty. Please provide a valid JSON object.")
            if not isinstance(request.json, dict):
                raise errors.ValidationError(message="The request body is not a valid JSON object.")
            validator.validate(request.json, keep_sensitive=True)
            return empty(204)

        return "/storage_schema/validate", ["POST"], _validate

    def obscure(self) -> BlueprintFactoryResponse:
        """Obscure values in config."""

        async def _obscure(request: Request, validator: RCloneValidator) -> JSONResponse:
            if not request.json:
                raise errors.ValidationError(message="The request body is empty. Please provide a valid JSON object.")
            if not isinstance(request.json, dict):
                raise errors.ValidationError(message="The request body is not a valid JSON object.")
            config = await validator.obscure_config(request.json)
            return json(config)

        return "/storage_schema/obscure", ["POST"], _obscure
