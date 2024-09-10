"""Search/reprovisioning blueprint."""

from dataclasses import dataclass

from sanic import HTTPResponse, Request, json
from sanic.response import JSONResponse

import renku_data_services.base_models as base_models
from renku_data_services.base_api.auth import authenticate, only_authenticated
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint


@dataclass(kw_only=True)
class SearchBP(CustomBlueprint):
    """Handlers for search."""

    authenticator: base_models.Authenticator

    def post(self) -> BlueprintFactoryResponse:
        """Start a new reprovisioning."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _post(_: Request, user: base_models.APIUser) -> HTTPResponse:
            # project = project_models.UnsavedProject(
            #     name=body.name,
            #     namespace=body.namespace,
            #     slug=body.slug or base_models.Slug.from_name(body.name).value,
            #     description=body.description,
            #     repositories=body.repositories or [],
            #     created_by=user.id,  # type: ignore[arg-type]
            #     visibility=Visibility(body.visibility.value),
            #     keywords=keywords,
            # )
            # result = await self.project_repo.insert_project(user, project)
            return HTTPResponse(status=201)

        return "/search/reprovision", ["POST"], _post

    def get_status(self) -> BlueprintFactoryResponse:
        """Get reprovisioning status."""

        @authenticate(self.authenticator)
        async def _get_status(_: Request, __: base_models.APIUser) -> JSONResponse | HTTPResponse:
            return json({"active": True}, 200)

        return "/search/reprovision", ["GET"], _get_status

    def delete(self) -> BlueprintFactoryResponse:
        """Stop reprovisioning (if any)."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete(_: Request, __: base_models.APIUser) -> HTTPResponse:
            # await self.project_repo.delete_project(user=user, project_id=ULID.from_str(project_id))
            return HTTPResponse(status=204)

        return "/search/reprovision", ["DELETE"], _delete
