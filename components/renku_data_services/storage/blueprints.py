"""Cloud storage app."""
from dataclasses import dataclass
from typing import Any

from sanic import Request, empty, json
from sanic_ext import validate

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.base_api.auth import authenticate
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.storage import apispec, models
from renku_data_services.storage.apispec_base import RepositoryFilter, SchemaValidationArguments
from renku_data_services.storage.db import StorageRepository
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
        async def _get(request: Request, validator: RCloneValidator, user: base_models.APIUser):
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
            storage_id: str,
            validator: RCloneValidator,
            user: base_models.APIUser,
        ):
            storage = await self.storage_repo.get_storage_by_id(storage_id, user=user)

            return json(dump_storage_with_sensitive_fields(storage, validator))

        return "/storage/<storage_id>", ["GET"], _get_one

    def post(self) -> BlueprintFactoryResponse:
        """Create a new cloud storage entry."""

        @authenticate(self.authenticator)
        async def _post(request: Request, validator: RCloneValidator, user: base_models.APIUser):
            storage: models.CloudStorage

            if "storage_url" in request.json:
                url_body = apispec.CloudStorageUrl(**request.json)
                storage = models.CloudStorage.from_url(
                    storage_url=url_body.storage_url,
                    project_id=url_body.project_id,
                    name=url_body.name,
                    target_path=url_body.target_path,
                    private=url_body.private,
                    readonly=url_body.readonly,
                )
            else:
                body = apispec.CloudStorage(**request.json)
                storage = models.CloudStorage.from_dict(body.model_dump())

            validator.validate(storage.configuration.model_dump(), private=storage.private)

            res = await self.storage_repo.insert_storage(storage=storage, user=user)
            return json(dump_storage_with_sensitive_fields(res, validator), 201)

        return "/storage", ["POST"], _post

    def put(self) -> BlueprintFactoryResponse:
        """Replace a storage entry."""

        @authenticate(self.authenticator)
        async def _put(
            request: Request,
            storage_id: str,
            validator: RCloneValidator,
            user: base_models.APIUser,
        ):
            if not request.json:
                raise errors.ValidationError(message="The request body is empty. Please provide a valid JSON object.")
            if not isinstance(request.json, dict):
                raise errors.ValidationError(message="The request body is not a valid JSON object.")
            if "storage_url" in request.json:
                url_body = apispec.CloudStorageUrl(**request.json)
                new_storage = models.CloudStorage.from_url(
                    storage_url=url_body.storage_url,
                    project_id=url_body.project_id,
                    name=url_body.name,
                    target_path=url_body.target_path,
                    private=url_body.private,
                    readonly=url_body.readonly,
                )
            else:
                body = apispec.CloudStorage(**request.json)
                new_storage = models.CloudStorage.from_dict(body.model_dump())

            validator.validate(new_storage.configuration.model_dump(), private=new_storage.private)
            body_dict = new_storage.model_dump()
            del body_dict["storage_id"]
            res = await self.storage_repo.update_storage(storage_id=storage_id, user=user, **body_dict)
            return json(dump_storage_with_sensitive_fields(res, validator))

        return "/storage/<storage_id>", ["PUT"], _put

    def patch(self) -> BlueprintFactoryResponse:
        """Update parts of a storage entry."""

        @authenticate(self.authenticator)
        @validate(json=apispec.CloudStoragePatch)
        async def _patch(
            request: Request,
            storage_id: str,
            body: apispec.CloudStoragePatch,
            validator: RCloneValidator,
            user: base_models.APIUser,
        ):
            existing_storage = await self.storage_repo.get_storage_by_id(storage_id, user=user)
            if not body.private and existing_storage.private:
                # remove sensitive option if storage is turned public
                config = existing_storage.configuration.model_copy()
                validator.remove_sensitive_options_from_config(config)
                body.configuration = {**config, **(body.configuration or {})}

            if body.configuration is not None:
                # we need to apply the patch to the existing storage to properly validate it
                body.configuration = {**existing_storage.configuration, **body.configuration}
                for k, v in list(body.configuration.items()):
                    if v is None:
                        # delete fields that were unset
                        del body.configuration[k]
                validator.validate(
                    body.configuration, private=body.private if body.private is not None else existing_storage.private
                )

            body_dict = body.model_dump(exclude_none=True)

            res = await self.storage_repo.update_storage(storage_id=storage_id, user=user, **body_dict)
            return json(dump_storage_with_sensitive_fields(res, validator))

        return "/storage/<storage_id>", ["PATCH"], _patch

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a storage entry."""

        @authenticate(self.authenticator)
        async def _delete(request: Request, storage_id: str, user: base_models.APIUser):
            await self.storage_repo.delete_storage(storage_id=storage_id, user=user)
            return empty(204)

        return "/storage/<storage_id>", ["DELETE"], _delete


@dataclass(kw_only=True)
class StorageSchemaBP(CustomBlueprint):
    """Handler for getting RClone storage schema."""

    def get(self) -> BlueprintFactoryResponse:
        """Get cloud storage for a repository."""

        async def _get(_: Request, validator: RCloneValidator):
            return json(validator.asdict())

        return "/storage_schema", ["GET"], _get

    def validate(self) -> BlueprintFactoryResponse:
        """Validate an RClone config."""

        async def _validate(request: Request, validator: RCloneValidator):
            validation_args = SchemaValidationArguments.model_validate(dict(request.query_args))
            if not request.json:
                raise errors.ValidationError(message="The request body is empty. Please provide a valid JSON object.")
            if not isinstance(request.json, dict):
                raise errors.ValidationError(message="The request body is not a valid JSON object.")
            if not request.json.get("configuration"):
                raise errors.ValidationError(message="No 'configuration' sent.")
            validator.validate(request.json["configuration"], private=True, keep_sensitive=True)
            if not validation_args.test_connection:
                return empty(204)
            if not request.json.get("source_path"):
                raise errors.ValidationError(message="'source_path' is required to test the connection.")
            result = await validator.test_connection(request.json["configuration"], request.json["source_path"])
            if not result.success:
                raise errors.ValidationError(message=result.error)
            return empty(204)

        return "/storage_schema/validate", ["POST"], _validate
