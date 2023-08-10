"""Cloud storage app."""
from dataclasses import asdict, dataclass

from sanic import Request, Sanic, json
from sanic_ext import validate

import renku_data_services.base_models as base_models
import renku_data_services.storage_models as models
from renku_data_services.base_api.auth import authenticate, only_admins
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.error_handler import CustomErrorHandler
from renku_data_services.storage_adapters import StorageRepository
from renku_data_services.storage_api.config import Config
from renku_data_services.storage_schemas import apispec, query_parameters
from renku_data_services.storage_schemas.core import RCloneValidator


@dataclass(kw_only=True)
class StorageBP(CustomBlueprint):
    """Handlers for manipulating storage definitions."""

    storage_repo: StorageRepository
    authenticator: base_models.Authenticator

    def get(self) -> BlueprintFactoryResponse:
        """Get cloud storage for a repository."""

        @authenticate(self.authenticator)
        async def _get(request: Request, user: base_models.APIUser):
            res_filter = query_parameters.RepositoryFilter.parse_obj(dict(request.query_args))
            storage: list[models.CloudStorage]
            storage = await self.storage_repo.get_storage(**res_filter.dict())

            return json([apispec.CloudStorageWithId.from_orm(s).dict(exclude_none=True) for s in storage])

        return "/storage", ["GET"], _get

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a single storage by id."""

        @authenticate(self.authenticator)
        async def _get_one(request: Request, storage_id: str, user: base_models.APIUser):
            storage = await self.storage_repo.get_storage_by_id(storage_id)

            return json(apispec.CloudStorageWithId.from_orm(storage).dict(exclude_none=True))

        return "/storage/<storage_id>", ["GET"], _get_one

    def post(self) -> BlueprintFactoryResponse:
        """Create a new cloud storage entry."""

        @authenticate(self.authenticator)
        @only_admins
        async def _post(request: Request, validator: RCloneValidator, user: base_models.APIUser):
            storage: models.CloudStorage

            if "storage_url" in request.json:
                url_body = apispec.CloudStorageUrl(**request.json)
                storage = models.CloudStorage.from_url(
                    storage_url=url_body.storage_url, project_id=url_body.project_id, target_path=url_body.target_path
                )
            else:
                body = apispec.CloudStorage(**request.json)
                storage = models.CloudStorage.from_dict(body.dict())

            validator.validate(storage.configuration)

            res = await self.storage_repo.insert_storage(storage=storage)
            return json(apispec.CloudStorageWithId.from_orm(res).dict(exclude_none=True), 201)

        return "/storage", ["POST"], _post

    def put(self) -> BlueprintFactoryResponse:
        """Replace a storage entry."""

        @authenticate(self.authenticator)
        @only_admins
        async def _put(request: Request, storage_id: str, validator: RCloneValidator, user: base_models.User):
            if "storage_url" in request.json:
                url_body = apispec.CloudStorageUrl(**request.json)
                new_storage = models.CloudStorage.from_url(
                    storage_url=url_body.storage_url, project_id=url_body.project_id, target_path=url_body.target_path
                )
            else:
                body = apispec.CloudStorage(**request.json)
                new_storage = models.CloudStorage.from_dict(body.dict())

            validator.validate(new_storage.configuration)
            body_dict = asdict(new_storage)
            del body_dict["storage_id"]
            res = await self.storage_repo.update_storage(storage_id=storage_id, **body_dict)
            return json(apispec.CloudStorageWithId.from_orm(res).dict(exclude_none=True))

        return "/storage/<storage_id>", ["PUT"], _put

    def patch(self) -> BlueprintFactoryResponse:
        """Update parts of a storage entry."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.CloudStoragePatch)
        async def _patch(
            request: Request,
            storage_id: str,
            body: apispec.CloudStoragePatch,
            validator: RCloneValidator,
            user: base_models.User,
        ):
            if body.configuration is not None:
                # we need to apply the patch to the existing storage to properly validate it
                existing_storage = await self.storage_repo.get_storage_by_id(storage_id)
                body.configuration = {**existing_storage.configuration, **body.configuration}
                validator.validate(body.configuration)

            body_dict = body.dict(exclude_none=True)

            res = await self.storage_repo.update_storage(storage_id=storage_id, **body_dict)
            return json(apispec.CloudStorageWithId.from_orm(res).dict(exclude_none=True))

        return "/storage/<storage_id>", ["PATCH"], _patch

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a storage entry."""

        @authenticate(self.authenticator)
        @only_admins
        async def _delete(request: Request, storage_id: str, user: base_models.APIUser):
            await self.storage_repo.delete_storage(storage_id=storage_id)
            return json(None, 204)

        return "/storage/<storage_id>", ["DELETE"], _delete


@dataclass(kw_only=True)
class StorageSchemaBP(CustomBlueprint):
    """Handler for getting RClone storage schema."""

    def get(self) -> BlueprintFactoryResponse:
        """Get cloud storage for a repository."""

        async def _get(_: Request, validator: RCloneValidator):
            return json(validator.asdict())

        return "/storage_schema", ["GET"], _get


def register_all_handlers(app: Sanic, config: Config) -> Sanic:
    """Register all handlers on the application."""
    url_prefix = "/api/storage"
    storage = StorageBP(
        name="storage",
        url_prefix=url_prefix,
        storage_repo=config.storage_repo,
        authenticator=config.authenticator,
    )
    storage_schema = StorageSchemaBP(name="storage_schema", url_prefix=url_prefix)

    app.blueprint(
        [
            storage.blueprint(),
            storage_schema.blueprint(),
        ]
    )

    app.error_handler = CustomErrorHandler(apispec)
    app.config.OAS = False
    app.config.OAS_UI_REDOC = False
    app.config.OAS_UI_SWAGGER = False
    app.config.OAS_AUTODOC = False
    return app
