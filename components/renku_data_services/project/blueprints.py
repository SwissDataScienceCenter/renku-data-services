"""Project blueprint."""

from dataclasses import dataclass
from typing import Any

from sanic import HTTPResponse, Request, json
from sanic.response import JSONResponse
from sanic_ext import validate
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services.authz.models import Member, Role, Visibility
from renku_data_services.base_api.auth import (
    authenticate,
    only_authenticated,
    validate_path_project_id,
    validate_path_user_id,
)
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.etag import extract_if_none_match, if_match_required
from renku_data_services.base_api.misc import validate_body_root_model, validate_query
from renku_data_services.base_api.pagination import PaginationRequest, paginate
from renku_data_services.base_models.validation import validate_and_dump, validated_json
from renku_data_services.errors import errors
from renku_data_services.project import apispec
from renku_data_services.project import models as project_models
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
        @validate_query(query=apispec.ProjectGetQuery)
        @paginate
        async def _get_all(
            _: Request, user: base_models.APIUser, pagination: PaginationRequest, query: apispec.ProjectGetQuery
        ) -> tuple[list[dict[str, Any]], int]:
            projects, total_num = await self.project_repo.get_projects(
                user=user, pagination=pagination, namespace=query.namespace, direct_member=query.direct_member
            )
            return [validate_and_dump(apispec.Project, self._dump_project(p)) for p in projects], total_num

        return "/projects", ["GET"], _get_all

    def post(self) -> BlueprintFactoryResponse:
        """Create a new project."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.ProjectPost)
        async def _post(_: Request, user: base_models.APIUser, body: apispec.ProjectPost) -> JSONResponse:
            keywords = [kw.root for kw in body.keywords] if body.keywords is not None else []
            project = project_models.UnsavedProject(
                name=body.name,
                namespace=body.namespace,
                slug=body.slug or base_models.Slug.from_name(body.name).value,
                description=body.description,
                repositories=body.repositories or [],
                created_by=user.id,  # type: ignore[arg-type]
                visibility=Visibility(body.visibility.value),
                keywords=keywords,
            )
            result = await self.project_repo.insert_project(user, project)
            return validated_json(apispec.Project, self._dump_project(result), status=201)

        return "/projects", ["POST"], _post

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific project."""

        @authenticate(self.authenticator)
        @validate_path_project_id
        @extract_if_none_match
        async def _get_one(
            _: Request, user: base_models.APIUser, project_id: str, etag: str | None
        ) -> JSONResponse | HTTPResponse:
            project = await self.project_repo.get_project(user=user, project_id=ULID.from_str(project_id))

            if project.etag is not None and project.etag == etag:
                return HTTPResponse(status=304)

            headers = {"ETag": project.etag} if project.etag is not None else None
            return validated_json(apispec.Project, self._dump_project(project), headers=headers)

        return "/projects/<project_id>", ["GET"], _get_one

    def get_one_by_namespace_slug(self) -> BlueprintFactoryResponse:
        """Get a specific project by namespace/slug."""

        @authenticate(self.authenticator)
        @extract_if_none_match
        async def _get_one_by_namespace_slug(
            _: Request, user: base_models.APIUser, namespace: str, slug: str, etag: str | None
        ) -> JSONResponse | HTTPResponse:
            project = await self.project_repo.get_project_by_namespace_slug(user=user, namespace=namespace, slug=slug)

            if project.etag is not None and project.etag == etag:
                return HTTPResponse(status=304)

            headers = {"ETag": project.etag} if project.etag is not None else None
            return validated_json(apispec.Project, self._dump_project(project), headers=headers)

        return "/projects/<namespace>/<slug:renku_slug>", ["GET"], _get_one_by_namespace_slug

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific project."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate_path_project_id
        async def _delete(_: Request, user: base_models.APIUser, project_id: str) -> HTTPResponse:
            await self.project_repo.delete_project(user=user, project_id=ULID.from_str(project_id))
            return HTTPResponse(status=204)

        return "/projects/<project_id>", ["DELETE"], _delete

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update a specific project."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate_path_project_id
        @if_match_required
        @validate(json=apispec.ProjectPatch)
        async def _patch(
            _: Request, user: base_models.APIUser, project_id: str, body: apispec.ProjectPatch, etag: str
        ) -> JSONResponse:
            body_dict = body.model_dump(exclude_none=True)

            project_update = await self.project_repo.update_project(
                user=user, project_id=ULID.from_str(project_id), etag=etag, payload=body_dict
            )
            if not isinstance(project_update, project_models.ProjectUpdate):
                raise errors.ProgrammingError(
                    message="Expected the result of a project update to be ProjectUpdate but instead "
                    f"got {type(project_update)}"
                )

            updated_project = project_update.new
            return validated_json(apispec.Project, self._dump_project(updated_project))

        return "/projects/<project_id>", ["PATCH"], _patch

    def get_all_members(self) -> BlueprintFactoryResponse:
        """List all project members."""

        @authenticate(self.authenticator)
        @validate_path_project_id
        async def _get_all_members(_: Request, user: base_models.APIUser, project_id: str) -> JSONResponse:
            members = await self.project_member_repo.get_members(user, ULID.from_str(project_id))

            users = []

            for member in members:
                user_id = member.user_id
                user_info = await self.user_repo.get_user(id=user_id)
                if not user_info:
                    raise errors.MissingResourceError(message=f"The user with ID {user_id} cannot be found.")
                namespace_info = user_info.namespace

                user_with_id = apispec.ProjectMemberResponse(
                    id=user_id,
                    namespace=namespace_info.slug,
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
        @validate_path_project_id
        @validate_body_root_model(json=apispec.ProjectMemberListPatchRequest)
        async def _update_members(
            _: Request, user: base_models.APIUser, project_id: str, body: apispec.ProjectMemberListPatchRequest
        ) -> HTTPResponse:
            members = [Member(Role(i.role.value), i.id, project_id) for i in body.root]
            await self.project_member_repo.update_members(user, ULID.from_str(project_id), members)
            return HTTPResponse(status=200)

        return "/projects/<project_id>/members", ["PATCH"], _update_members

    def delete_member(self) -> BlueprintFactoryResponse:
        """Delete a specific project."""

        @authenticate(self.authenticator)
        @validate_path_project_id
        @validate_path_user_id
        async def _delete_member(
            _: Request, user: base_models.APIUser, project_id: str, member_id: str
        ) -> HTTPResponse:
            await self.project_member_repo.delete_members(user, ULID.from_str(project_id), [member_id])
            return HTTPResponse(status=204)

        return "/projects/<project_id>/members/<member_id>", ["DELETE"], _delete_member

    def get_permissions(self) -> BlueprintFactoryResponse:
        """Get the permissions of the current user on the project."""

        @authenticate(self.authenticator)
        @validate_path_project_id
        async def _get_permissions(_: Request, user: base_models.APIUser, project_id: str) -> JSONResponse:
            permissions = await self.project_repo.get_project_permissions(
                user=user, project_id=ULID.from_str(project_id)
            )
            return validated_json(apispec.ProjectPermissions, permissions)

        return "/projects/<project_id>/permissions", ["GET"], _get_permissions

    @staticmethod
    def _dump_project(project: project_models.Project) -> dict[str, Any]:
        """Dumps a project for API responses."""
        return dict(
            id=str(project.id),
            name=project.name,
            namespace=project.namespace.slug,
            slug=project.slug,
            creation_date=project.creation_date.isoformat(),
            created_by=project.created_by,
            updated_at=project.updated_at.isoformat() if project.updated_at else None,
            repositories=project.repositories,
            visibility=project.visibility.value,
            description=project.description,
            etag=project.etag,
            keywords=project.keywords or [],
        )
