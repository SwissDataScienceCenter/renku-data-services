"""Cloud storage app."""

from dataclasses import dataclass
from typing import Any

from sanic import HTTPResponse, Request, empty
from sanic.response import JSONResponse
from sanic_ext import validate
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.base_api.auth import authenticate
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.misc import validate_body_root_model, validate_query
from renku_data_services.base_models.validation import validated_json
from renku_data_services.storage import apispec, models
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


def dump_storage_with_sensitive_fields_and_secrets(
    storage: models.CloudStorage, validator: RCloneValidator
) -> dict[str, Any]:
    """Dump a CloudStorage model alongside sensitive fields and its saved secrets."""
    dumped_storage = dump_storage_with_sensitive_fields(storage, validator)
    dumped_storage["secrets"] = [apispec.CloudStorageSecretGet.model_validate(s).model_dump() for s in storage.secrets]
    return dumped_storage


@dataclass(kw_only=True)
class StorageBP(CustomBlueprint):
    """Handlers for manipulating storage definitions."""

    storage_repo: StorageRepository
    authenticator: base_models.Authenticator

    def get(self) -> BlueprintFactoryResponse:
        """Get cloud storage for a repository."""

        @authenticate(self.authenticator)
        @validate_query(query=apispec.StorageParams)
        async def _get(
            request: Request,
            user: base_models.APIUser,
            validator: RCloneValidator,
            query: apispec.StorageParams,
        ) -> JSONResponse:
            storage = await self.storage_repo.get_storage(user=user, project_id=query.project_id)

            return validated_json(
                apispec.StorageGetResponse, [dump_storage_with_sensitive_fields(s, validator) for s in storage]
            )

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

            return validated_json(apispec.CloudStorageGet, dump_storage_with_sensitive_fields(storage, validator))

        return "/storage/<storage_id:ulid>", ["GET"], _get_one

    def post(self) -> BlueprintFactoryResponse:
        """Create a new cloud storage entry."""

        @authenticate(self.authenticator)
        async def _post(request: Request, user: base_models.APIUser, validator: RCloneValidator) -> JSONResponse:
            storage: models.UnsavedCloudStorage
            if not isinstance(request.json, dict):
                body_type = type(request.json)
                raise errors.ValidationError(
                    message=f"The payload is supposed to be a dictionary, got {body_type.__name__}"
                )
            if "storage_url" in request.json:
                url_body = apispec.CloudStorageUrl(**request.json)
                storage = models.UnsavedCloudStorage.from_url(
                    storage_url=url_body.storage_url,
                    project_id=url_body.project_id.root,
                    name=url_body.name,
                    target_path=url_body.target_path,
                    readonly=url_body.readonly,
                )
            else:
                body = apispec.CloudStorage(**request.json)
                storage = models.UnsavedCloudStorage.from_dict(body.model_dump())

            validator.validate(storage.configuration.model_dump())

            res = await self.storage_repo.insert_storage(storage=storage, user=user)
            return validated_json(apispec.CloudStorageGet, dump_storage_with_sensitive_fields(res, validator), 201)

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
                new_storage = models.UnsavedCloudStorage.from_url(
                    storage_url=url_body.storage_url,
                    project_id=url_body.project_id.root,
                    name=url_body.name,
                    target_path=url_body.target_path,
                    readonly=url_body.readonly,
                )
            else:
                body = apispec.CloudStorage(**request.json)
                new_storage = models.UnsavedCloudStorage.from_dict(body.model_dump())

            validator.validate(new_storage.configuration.model_dump())
            body_dict = new_storage.model_dump()
            res = await self.storage_repo.update_storage(storage_id=storage_id, user=user, **body_dict)
            return validated_json(apispec.CloudStorageGet, dump_storage_with_sensitive_fields(res, validator))

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
            return validated_json(apispec.CloudStorageGet, dump_storage_with_sensitive_fields(res, validator))

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
        @validate_query(query=apispec.StorageV2Params)
        async def _get(
            request: Request,
            user: base_models.APIUser,
            validator: RCloneValidator,
            query: apispec.StorageV2Params,
        ) -> JSONResponse:
            storage = await self.storage_v2_repo.get_storage(
                user=user, include_secrets=True, project_id=ULID.from_str(query.project_id)
            )

            return validated_json(
                apispec.StoragesV2GetResponse,
                [dump_storage_with_sensitive_fields_and_secrets(s, validator) for s in storage],
            )

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

            return validated_json(
                apispec.CloudStorageGetV2, dump_storage_with_sensitive_fields_and_secrets(storage, validator)
            )

        return "/storages_v2/<storage_id:ulid>", ["GET"], _get_one

    def post(self) -> BlueprintFactoryResponse:
        """Create a new cloud storage entry."""

        @authenticate(self.authenticator)
        async def _post(request: Request, user: base_models.APIUser, validator: RCloneValidator) -> JSONResponse:
            storage: models.UnsavedCloudStorage
            if not isinstance(request.json, dict):
                body_type = type(request.json)
                raise errors.ValidationError(
                    message=f"The payload is supposed to be a dictionary, got {body_type.__name__}"
                )
            if "storage_url" in request.json:
                url_body = apispec.CloudStorageUrl(**request.json)
                storage = models.UnsavedCloudStorage.from_url(
                    storage_url=url_body.storage_url,
                    project_id=url_body.project_id.root,
                    name=url_body.name,
                    target_path=url_body.target_path,
                    readonly=url_body.readonly,
                )
            else:
                body = apispec.CloudStorage(**request.json)
                storage = models.UnsavedCloudStorage.from_dict(body.model_dump())

            validator.validate(storage.configuration.model_dump())

            res = await self.storage_v2_repo.insert_storage(storage=storage, user=user)
            return validated_json(apispec.CloudStorageGet, dump_storage_with_sensitive_fields(res, validator), 201)

        return "/storages_v2", ["POST"], _post

    def patch(self) -> BlueprintFactoryResponse:
        """Update parts of a storage entry."""

        @authenticate(self.authenticator)
        @validate(json=apispec.CloudStoragePatch)
        async def _patch(
            _: Request,
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
            return validated_json(apispec.CloudStorageGet, dump_storage_with_sensitive_fields(res, validator))

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
        @validate_body_root_model(json=apispec.CloudStorageSecretPostList)
        async def _upsert_secrets(
            _: Request, user: base_models.APIUser, storage_id: ULID, body: apispec.CloudStorageSecretPostList
        ) -> JSONResponse:
            secrets = [models.CloudStorageSecretUpsert.model_validate(s.model_dump()) for s in body.root]
            result = await self.storage_v2_repo.upsert_storage_secrets(
                storage_id=storage_id, user=user, secrets=secrets
            )
            return validated_json(apispec.CloudStorageSecretGetList, result, 201)

        return "/storages_v2/<storage_id:ulid>/secrets", ["POST"], _upsert_secrets

    def get_secrets(self) -> BlueprintFactoryResponse:
        """Return all secrets for a cloud storage."""

        @authenticate(self.authenticator)
        async def _get_secrets(request: Request, user: base_models.APIUser, storage_id: ULID) -> JSONResponse:
            result = await self.storage_v2_repo.get_storage_secrets(storage_id=storage_id, user=user)
            return validated_json(apispec.CloudStorageSecretGetList, result, 200)

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
            return validated_json(apispec.RCloneSchema, validator.asdict())

        return "/storage_schema", ["GET"], _get

    def test_connection(self) -> BlueprintFactoryResponse:
        """Validate an RClone config."""

        @validate(json=apispec.StorageSchemaTestConnectionPostRequest)
        async def _test_connection(
            request: Request, validator: RCloneValidator, body: apispec.StorageSchemaTestConnectionPostRequest
        ) -> HTTPResponse:
            validator.validate(body.configuration, keep_sensitive=True)
            result = await validator.test_connection(body.configuration, body.source_path)
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
