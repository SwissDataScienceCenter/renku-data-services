"""Project blueprint."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import cast

from sanic import HTTPResponse, Request, json
from sanic_ext import validate

import renku_data_services.base_models as base_models
from renku_data_services.base_api.auth import authenticate, only_authenticated
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.errors import errors
from renku_data_services.project import apispec, models
from renku_data_services.project.apispec import FullUserWithRole, UserWithId
from renku_data_services.project.db import ProjectMemberRepository, ProjectRepository
from renku_data_services.users.db import UserRepo


@dataclass(kw_only=True)
class ProjectsBP(CustomBlueprint):
    """Handlers for manipulating projects."""

    project_repo: ProjectRepository
    project_member_repo: ProjectMemberRepository
    user_repo: UserRepo
    authenticator: base_models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """List all projects."""

        @authenticate(self.authenticator)
        async def _get_all(request: Request, *, user: base_models.APIUser):
            default_page_number = 1
            default_number_of_elements_per_page = 20

            args = request.args if request.args else {}
            page_parameter = args.get("page", default_page_number)
            try:
                page = int(page_parameter)
            except ValueError:
                raise errors.ValidationError(message=f"Invalid value for parameter 'page': {page_parameter}")
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
            user_id: str = cast(str, user.id)
            data["created_by"] = models.Member(id=user_id)
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
            headers = {"ETag": project.etag} if project.etag is not None else None
            return json(
                apispec.Project.model_validate(project).model_dump(exclude_none=True, mode="json"), headers=headers
            )

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

    def get_all_members(self) -> BlueprintFactoryResponse:
        """List all project members."""

        @authenticate(self.authenticator)
        async def _get_all_members(_: Request, *, user: base_models.APIUser, project_id: str):
            members = await self.project_member_repo.get_members(user=user, project_id=project_id)

            users = []

            for member in members:
                user_id = member.member.id
                user_info = await self.user_repo.get_user(requested_by=user, id=user_id)
                if not user_info:
                    raise errors.MissingResourceError(message=f"The user with ID {user_id} cannot be found.")

                user_with_id = UserWithId(
                    id=user_id, email=user_info.email, first_name=user_info.first_name, last_name=user_info.last_name
                )
                full_user = FullUserWithRole(member=user_with_id, role=member.role)
                users.append(full_user)

            return json(
                [apispec.FullUserWithRole.model_validate(u).model_dump(exclude_none=True, mode="json") for u in users]
            )

        return "/projects/<project_id>/members", ["GET"], _get_all_members

    def update_members(self) -> BlueprintFactoryResponse:
        """Update or add project members."""

        @authenticate(self.authenticator)
        async def _update_members(request: Request, *, user: base_models.APIUser, project_id: str):
            body_dump = apispec.MembersWithRoles.model_validate(request.json).model_dump(exclude_none=True)
            await self.project_member_repo.update_members(
                user=user,
                project_id=project_id,
                members=body_dump,  # type: ignore[arg-type]
            )
            return HTTPResponse(status=200)

        return "/projects/<project_id>/members", ["PATCH"], _update_members

    def delete_member(self) -> BlueprintFactoryResponse:
        """Delete a specific project."""

        @authenticate(self.authenticator)
        async def _delete_member(_: Request, *, user: base_models.APIUser, project_id: str, member_id: str):
            await self.project_member_repo.delete_member(user=user, project_id=project_id, member_id=member_id)
            return HTTPResponse(status=204)

        return "/projects/<project_id>/members/<member_id>", ["DELETE"], _delete_member
