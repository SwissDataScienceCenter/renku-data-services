"""Project blueprint."""

from dataclasses import dataclass
from datetime import datetime, timezone

from sanic import HTTPResponse, Request, json
from sanic_ext import validate

import renku_data_services.base_models as base_models
from renku_data_services.base_api.auth import authenticate, only_authenticated
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.errors import errors
from renku_data_services.project import apispec, models
from renku_data_services.project.db import ProjectRepository


@dataclass(kw_only=True)
class ProjectsBP(CustomBlueprint):
    """Handlers for manipulating projects."""

    project_repo: ProjectRepository
    authenticator: base_models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """List all projects."""

        @authenticate(self.authenticator)
        async def _get_all(request: Request, *, user: base_models.APIUser):
            default_page_number = 1
            default_number_of_elements_per_page = 20

            args = request.args if request.args else {}
            page = int(args.get("page", default_page_number))
            per_page = int(args.get("per_page", default_number_of_elements_per_page))

            projects, pagination = await self.project_repo.get_projects(user=user, page=page, per_page=per_page)
            return json(
                [apispec.Project.model_validate(p).model_dump(exclude_none=True, mode="json") for p in projects],
                headers={
                    "page": str(pagination.page),
                    "per-page": str(pagination.per_page),
                    "total": str(pagination.total),
                    "total-pages": str(pagination.total_pages),
                },
            )

        return "/projects", ["GET"], _get_all

    def post(self) -> BlueprintFactoryResponse:
        """Create a new project."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.ProjectPost)
        async def _post(_: Request, *, user: base_models.APIUser, body: apispec.ProjectPost):
            data = body.model_dump(exclude_none=True)
            if user.id:
                data["created_by"] = models.User(id=user.id)
            # NOTE: Set ``creation_date`` to override possible value set by users
            data["creation_date"] = datetime.now(timezone.utc).replace(microsecond=0)
            project = models.Project.from_dict(data)
            result = await self.project_repo.insert_project(user=user, project=project)
            return json(apispec.Project.model_validate(result).model_dump(exclude_none=True, mode="json"), 201)

        return "/projects", ["POST"], _post

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific project."""

        @authenticate(self.authenticator)
        async def _get_one(_: Request, *, user: base_models.APIUser, project_id: str):
            project = await self.project_repo.get_project(user=user, project_id=project_id)
            return json(apispec.Project.model_validate(project).model_dump(exclude_none=True, mode="json"))

        return "/projects/<project_id>", ["GET"], _get_one

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific project."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete(_: Request, *, user: base_models.APIUser, project_id: str):
            await self.project_repo.delete_project(user=user, project_id=project_id)
            return HTTPResponse(status=204)

        return "/projects/<project_id>", ["DELETE"], _delete

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update a specific project."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.ProjectPatch)
        async def _patch(_: Request, *, user: base_models.APIUser, project_id: str, body: apispec.ProjectPatch):
            body_dict = body.model_dump(exclude_none=True)

            updated_project = await self.project_repo.update_project(user=user, project_id=project_id, **body_dict)

            return json(apispec.Project.model_validate(updated_project).model_dump(exclude_none=True, mode="json"))

        return "/projects/<project_id>", ["PATCH"], _patch
