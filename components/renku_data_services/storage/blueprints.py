"""Cloud storage app."""

from dataclasses import dataclass

from sanic import HTTPResponse, Request, empty
from sanic.response import JSONResponse
from sanic_ext import validate

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.base_api.auth import authenticate
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_models.validation import validated_json
from renku_data_services.notebooks.data_sources import DataSourceRepository
from renku_data_services.storage import apispec
from renku_data_services.storage.rclone import RenkuRCloneValidator


@dataclass(kw_only=True)
class StorageSchemaBP(CustomBlueprint):
    """Handler for getting RClone storage schema."""

    data_source_repo: DataSourceRepository
    authenticator: base_models.Authenticator

    def get(self) -> BlueprintFactoryResponse:
        """Get cloud storage for a repository."""

        async def _get(_: Request, validator: RenkuRCloneValidator) -> JSONResponse:
            return validated_json(apispec.RCloneSchema, validator.asdict())

        return "/storage_schema", ["GET"], _get

    def test_connection(self) -> BlueprintFactoryResponse:
        """Validate an RClone config."""

        @authenticate(self.authenticator)
        @validate(json=apispec.StorageSchemaTestConnectionPostRequest)
        async def _test_connection(
            request: Request,
            user: base_models.APIUser,
            validator: RenkuRCloneValidator,
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
            request: Request, validator: RenkuRCloneValidator, body: apispec.RCloneConfigValidate
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
            request: Request, validator: RenkuRCloneValidator, body: apispec.StorageSchemaObscurePostRequest
        ) -> JSONResponse:
            config = await validator.obscure_config(body.configuration)
            return validated_json(apispec.RCloneConfigValidate, config)

        return "/storage_schema/obscure", ["POST"], _obscure
