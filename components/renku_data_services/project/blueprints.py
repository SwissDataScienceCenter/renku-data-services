"""Project blueprint."""

from dataclasses import dataclass

from sanic import HTTPResponse, Request, json
from sanic_ext import validate

import renku_data_services.base_models as base_models
from renku_data_services.base_api.auth import authenticate, only_authenticated
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.etag import if_match_required
from renku_data_services.base_api.pagination import PaginationRequest, paginate
from renku_data_services.errors import errors
from renku_data_services.project import apispec
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
        @paginate
        async def _get_all(_: Request, *, user: base_models.APIUser, pagination: PaginationRequest):
            projects, total_num = await self.project_repo.get_projects(user=user, pagination=pagination)
            return [
                apispec.Project.model_validate(p).model_dump(exclude_none=True, mode="json") for p in projects
            ], total_num

        return "/projects", ["GET"], _get_all

    def post(self) -> BlueprintFactoryResponse:
        """Create a new project."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.ProjectPost)
        async def _post(_: Request, *, user: base_models.APIUser, body: apispec.ProjectPost):
            project = await self.project_repo.insert_project(user=user, new_project=body)
            return json(apispec.Project.model_validate(project).model_dump(exclude_none=True, mode="json"), 201)

        return "/projects", ["POST"], _post

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific project."""

        @authenticate(self.authenticator)
        async def _get_one(request: Request, *, user: base_models.APIUser, project_id: str):
            project = await self.project_repo.get_project(user=user, project_id=project_id)

            etag = request.headers.get("If-None-Match")
            if project.etag is not None and project.etag == etag:
                return HTTPResponse(status=304)

            headers = {"ETag": project.etag} if project.etag is not None else None
            return json(
                apispec.Project.model_validate(project).model_dump(exclude_none=True, mode="json"), headers=headers
            )

        return "/projects/<project_id>", ["GET"], _get_one

    def get_one_by_namespace_slug(self) -> BlueprintFactoryResponse:
        """Get a specific project by namespace/slug."""

        @authenticate(self.authenticator)
        async def _get_one_by_namespace_slug(_: Request, *, user: base_models.APIUser, namespace: str, slug: str):
            project = await self.project_repo.get_project_by_namespace_slug(user=user, namespace=namespace, slug=slug)
            return json(apispec.Project.model_validate(project).model_dump(exclude_none=True, mode="json"))

        return "/projects/<namespace>/<slug>", ["GET"], _get_one_by_namespace_slug

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
        @if_match_required
        @validate(json=apispec.ProjectPatch)
        async def _patch(
            _: Request, *, user: base_models.APIUser, project_id: str, body: apispec.ProjectPatch, etag: str
        ):
            body_dict = body.model_dump(exclude_none=True)

            updated_project = await self.project_repo.update_project(
                user=user, project_id=project_id, etag=etag, **body_dict
            )

            return json(apispec.Project.model_validate(updated_project).model_dump(exclude_none=True, mode="json"))

        return "/projects/<project_id>", ["PATCH"], _patch

    def get_all_members(self) -> BlueprintFactoryResponse:
        """List all project members."""

        @authenticate(self.authenticator)
        async def _get_all_members(_: Request, *, user: base_models.APIUser, project_id: str):
            members = await self.project_member_repo.get_members(user=user, project_id=project_id)

            users = []

            for member in members:
                user_id = member.member
                user_info = await self.user_repo.get_user(requested_by=user, id=user_id)
                if not user_info:
                    raise errors.MissingResourceError(message=f"The user with ID {user_id} cannot be found.")

                user_with_id = apispec.ProjectMemberResponse(
                    id=user_id,
                    email=user_info.email,
                    first_name=user_info.first_name,
                    last_name=user_info.last_name,
                    role=apispec.Role(member.role.value),
                ).model_dump(exclude_none=True, mode="json")
                users.append(user_with_id)

            return json(users)

        return "/projects/<project_id>/members", ["GET"], _get_all_members

    def update_members(self) -> BlueprintFactoryResponse:
        """Update or add project members."""

        @authenticate(self.authenticator)
        async def _update_members(request: Request, *, user: base_models.APIUser, project_id: str):
            body_dump = apispec.ProjectMemberListPatchRequest.model_validate(request.json).model_dump(exclude_none=True)
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
