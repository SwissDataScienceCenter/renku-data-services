"""Project blueprint (v1)."""

from dataclasses import dataclass
from typing import Any

from sanic import Request
from sanic.response import JSONResponse
from sanic_ext import validate

import renku_data_services.base_models as base_models
from renku_data_services.base_api.auth import authenticate, only_authenticated
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.misc import validate_query
from renku_data_services.base_api.pagination import PaginationRequest, paginate
from renku_data_services.base_models.metrics import MetricsService, ProjectCreationType
from renku_data_services.base_models.validation import validate_and_dump, validated_json
from renku_data_services.project import apispec as apispec_latest
from renku_data_services.project import models as project_models
from renku_data_services.project.core import validate_unsaved_project
from renku_data_services.project.db import ProjectRepository
from renku_data_services.project.v1 import apispec


@dataclass(kw_only=True)
class ProjectsBP(CustomBlueprint):
    """Handlers for manipulating projects."""

    project_repo: ProjectRepository
    authenticator: base_models.Authenticator
    metrics: MetricsService

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
            new_project = validate_unsaved_project(
                apispec_latest.ProjectPost.model_validate(body), created_by=user.id or ""
            )
            result = await self.project_repo.insert_project(user, new_project)
            await self.metrics.project_created(user, metadata={"project_creation_kind": ProjectCreationType.new.value})
            if len(result.repositories) > 0:
                await self.metrics.code_repo_linked_to_project(user)
            return validated_json(apispec.Project, self._dump_project(result), status=201)

        return "/projects", ["POST"], _post

    @staticmethod
    def _dump_project(project: project_models.Project, with_documentation: bool = False) -> dict[str, Any]:
        """Dumps a project for API responses."""
        result = dict(
            id=project.id,
            name=project.name,
            namespace=project.namespace.path.serialize(),
            slug=project.slug,
            creation_date=project.creation_date.isoformat(),
            created_by=project.created_by,
            updated_at=project.updated_at.isoformat() if project.updated_at else None,
            repositories=project.repositories,
            visibility=project.visibility.value,
            description=project.description,
            etag=project.etag,
            keywords=project.keywords or [],
            template_id=project.template_id,
            is_template=project.is_template,
            secrets_mount_directory=str(project.secrets_mount_directory),
        )
        if with_documentation:
            result = dict(result, documentation=project.documentation)
        return result
