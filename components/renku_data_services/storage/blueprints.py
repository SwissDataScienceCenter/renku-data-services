"""Cloud storage app."""

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sanic import HTTPResponse, Request, empty
from sanic.response import JSONResponse
from sanic_ext import validate
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.base_api.auth import authenticate
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.misc import validate_query
from renku_data_services.base_models.validation import validated_json
from renku_data_services.notebooks.data_sources import DataSourceRepository
from renku_data_services.storage import apispec, models
from renku_data_services.storage.db import StorageRepository
from renku_data_services.storage.rclone import RCloneValidator


def dump_storage_with_sensitive_fields(storage: models.CloudStorage, validator: RCloneValidator) -> dict[str, Any]:
    """Dump a CloudStorage model alongside sensitive fields."""
    try:
        body = apispec.CloudStorageGet.model_validate(
            {
                "storage": apispec.CloudStorageWithId.model_validate(storage).model_dump(exclude_none=True),
                "sensitive_fields": [
                    option.model_dump(exclude_none=True, by_alias=True)
                    for option in validator.get_private_fields(storage.configuration)
                ],
            }
        ).model_dump(exclude_none=True)
    except PydanticValidationError as err:
        parts = [".".join(str(i) for i in field["loc"]) + ": " + field["msg"] for field in err.errors()]
        message = (
            f"The server could not construct a valid response. Errors found in the following fields: {', '.join(parts)}"
        )
        raise errors.ProgrammingError(message=message) from err
    return body


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
