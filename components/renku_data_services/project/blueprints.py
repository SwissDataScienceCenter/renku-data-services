"""Project blueprint."""

from dataclasses import dataclass
from datetime import timezone, datetime

from sanic import HTTPResponse, Request, json
from sanic_ext import validate

import renku_data_services.base_models as base_models
from renku_data_services.base_api.auth import authenticate
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
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
        async def _get_all(_: Request, user: base_models.APIUser):
            projects = await self.project_repo.get_projects(user=user)
            return json(
                [apispec.Project.model_validate(p).model_dump(exclude_none=True, mode="json") for p in projects]
            )

        return "/projects", ["GET"], _get_all

    def post(self) -> BlueprintFactoryResponse:
        """Create a new project."""

        @authenticate(self.authenticator)
        @validate(json=apispec.ProjectPost)
        async def _post(_: Request, body: apispec.ProjectPost, user: base_models.APIUser):
            data = body.model_dump(exclude_none=True)
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
        async def _get_one(_: Request, project_id: str, user: base_models.APIUser):
            project = await self.project_repo.get_project(user=user, id=project_id)
            return json(apispec.Project.model_validate(project).model_dump(exclude_none=True, mode="json"))

        return "/projects/<project_id>", ["GET"], _get_one

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific project."""

        @authenticate(self.authenticator)
        async def _delete(_: Request, project_id: str, user: base_models.APIUser):
            await self.project_repo.delete_project(user=user, id=project_id)
            return HTTPResponse(status=204)

        return "/projects/<project_id>", ["DELETE"], _delete

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update a specific project."""

        @authenticate(self.authenticator)
        @validate(json=apispec.ProjectPatch)
        async def _patch(_: Request, project_id: str, body: apispec.ProjectPatch, user: base_models.APIUser):
            body_dict = body.model_dump(exclude_none=True)

            updated_project = await self.project_repo.update_project(user=user, id=project_id, **body_dict)

            return json(apispec.Project.model_validate(updated_project).model_dump(exclude_none=True, mode="json"))

        return "/projects/<project_id>", ["PATCH"], _patch
