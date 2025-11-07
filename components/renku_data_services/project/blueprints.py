"""Project blueprint."""

from dataclasses import dataclass
from typing import Any

from sanic import HTTPResponse, Request
from sanic.response import JSONResponse
from sanic_ext import validate
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services.authz.models import Change, Member, Role, Visibility
from renku_data_services.base_api.auth import (
    authenticate,
    only_authenticated,
    validate_path_user_id,
)
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.etag import extract_if_none_match, if_match_required
from renku_data_services.base_api.misc import validate_body_root_model, validate_query
from renku_data_services.base_api.pagination import PaginationRequest, paginate
from renku_data_services.base_models.core import Slug
from renku_data_services.base_models.metrics import MetricsService, ProjectCreationType
from renku_data_services.base_models.validation import validate_and_dump, validated_json
from renku_data_services.data_connectors.db import DataConnectorRepository
from renku_data_services.errors import errors
from renku_data_services.project import apispec
from renku_data_services.project import models as project_models
from renku_data_services.project.core import (
    copy_project,
    validate_project_patch,
    validate_session_secret_slot_patch,
    validate_session_secrets_patch,
    validate_unsaved_project,
    validate_unsaved_session_secret_slot,
)
from renku_data_services.project.db import (
    ProjectMemberRepository,
    ProjectMigrationRepository,
    ProjectRepository,
    ProjectSessionSecretRepository,
)
from renku_data_services.session.db import SessionRepository
from renku_data_services.users.db import UserRepo


@dataclass(kw_only=True)
class ProjectsBP(CustomBlueprint):
    """Handlers for manipulating projects."""

    project_repo: ProjectRepository
    project_member_repo: ProjectMemberRepository
    user_repo: UserRepo
    authenticator: base_models.Authenticator
    data_connector_repo: DataConnectorRepository
    project_migration_repo: ProjectMigrationRepository
    session_repo: SessionRepository
    session_secret_repo: ProjectSessionSecretRepository
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
            new_project = validate_unsaved_project(body, created_by=user.id or "")
            result = await self.project_repo.insert_project(user, new_project)
            await self.metrics.project_created(user, metadata={"project_creation_kind": ProjectCreationType.new.value})
            if len(result.repositories) > 0:
                await self.metrics.code_repo_linked_to_project(user)
            return validated_json(apispec.Project, self._dump_project(result), status=201)

        return "/projects", ["POST"], _post

    def get_all_migrations(self) -> BlueprintFactoryResponse:
        """List all project migrations."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _get_all_migrations(_: Request, user: base_models.APIUser) -> JSONResponse:
            project_migrations = self.project_migration_repo.get_project_migrations(user=user)

            migrations_list = []
            async for migration in project_migrations:
                migrations_list.append(self._dump_project_migration(migration))

            return validated_json(apispec.ProjectMigrationList, migrations_list)

        return "/renku_v1_projects/migrations", ["GET"], _get_all_migrations

    def get_migration(self) -> BlueprintFactoryResponse:
        """Get project migration by project v1 id."""

        @authenticate(self.authenticator)
        async def _get_migration(_: Request, user: base_models.APIUser, v1_id: int) -> JSONResponse:
            project = await self.project_migration_repo.get_migration_by_v1_id(user, v1_id)
            project_dump = self._dump_project(project)
            return validated_json(apispec.Project, project_dump)

        return "/renku_v1_projects/<v1_id:int>/migrations", ["GET"], _get_migration

    def post_migration(self) -> BlueprintFactoryResponse:
        """Migrate v1 project."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.ProjectMigrationPost)
        async def _post_migration(
            _: Request, user: base_models.APIUser, v1_id: int, body: apispec.ProjectMigrationPost
        ) -> JSONResponse:
            new_project = validate_unsaved_project(body.project, created_by=user.id or "")

            result = await self.project_migration_repo.migrate_v1_project(
                user, project=new_project, project_v1_id=v1_id, session_launcher=body.session_launcher
            )
            await self.metrics.project_created(
                user, metadata={"project_creation_kind": ProjectCreationType.migrated.value}
            )
            return validated_json(apispec.Project, self._dump_project(result), status=201)

        return "/renku_v1_projects/<v1_id:int>/migrations", ["POST"], _post_migration

    def get_project_migration_info(self) -> BlueprintFactoryResponse:
        """Get project migration by project v2 id."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _get_project_migration_info(
            _: Request, user: base_models.APIUser, project_id: ULID
        ) -> JSONResponse | HTTPResponse:
            migration_info = await self.project_migration_repo.get_migration_by_project_id(user, project_id)

            if migration_info and isinstance(migration_info, project_models.ProjectMigrationInfo):
                dump_migration_info = dict(
                    project_id=migration_info.project_id,
                    v1_id=migration_info.v1_id,
                    launcher_id=migration_info.launcher_id,
                )
                return validated_json(apispec.ProjectMigrationInfo, dump_migration_info)

            return HTTPResponse(status=404)

        return "/projects/<project_id:ulid>/migration_info", ["GET"], _get_project_migration_info

    def copy(self) -> BlueprintFactoryResponse:
        """Create a new project by copying it from a template project."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.ProjectPost)
        async def _copy(
            _: Request, user: base_models.APIUser, project_id: ULID, body: apispec.ProjectPost
        ) -> JSONResponse:
            project = await copy_project(
                source_project_id=project_id,
                user=user,
                name=body.name,
                namespace=body.namespace,
                slug=body.slug,
                description=body.description,
                repositories=body.repositories,
                visibility=Visibility(body.visibility.value) if body.visibility is not None else None,
                keywords=[kw.root for kw in body.keywords] if body.keywords is not None else [],
                secrets_mount_directory=body.secrets_mount_directory,
                project_repo=self.project_repo,
                session_repo=self.session_repo,
                data_connector_repo=self.data_connector_repo,
                session_secret_repo=self.session_secret_repo,
            )
            await self.metrics.project_created(
                user, metadata={"project_creation_kind": ProjectCreationType.copied.value}
            )
            return validated_json(apispec.Project, self._dump_project(project), status=201)

        return "/projects/<project_id:ulid>/copies", ["POST"], _copy

    def get_all_copies(self) -> BlueprintFactoryResponse:
        """Get all copies of a specific project that the user has access to."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(query=apispec.ProjectsProjectIdCopiesGetParametersQuery)
        async def _get_all_copies(
            _: Request,
            user: base_models.APIUser,
            project_id: ULID,
            query: apispec.ProjectsProjectIdCopiesGetParametersQuery,
        ) -> JSONResponse:
            projects = await self.project_repo.get_all_copied_projects(
                user=user, project_id=project_id, only_writable=query.writable
            )
            projects_dump = [self._dump_project(p) for p in projects]
            return validated_json(apispec.ProjectsList, projects_dump)

        return "/projects/<project_id:ulid>/copies", ["GET"], _get_all_copies

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific project."""

        @authenticate(self.authenticator)
        @extract_if_none_match
        @validate_query(query=apispec.ProjectsProjectIdGetParametersQuery)
        async def _get_one(
            _: Request,
            user: base_models.APIUser,
            project_id: ULID,
            etag: str | None,
            query: apispec.ProjectsProjectIdGetParametersQuery,
        ) -> JSONResponse | HTTPResponse:
            with_documentation = query.with_documentation is True
            project = await self.project_repo.get_project(
                user=user, project_id=project_id, with_documentation=with_documentation
            )

            if project.etag is not None and project.etag == etag:
                return HTTPResponse(status=304)

            headers = {"ETag": project.etag} if project.etag is not None else None
            return validated_json(
                apispec.Project, self._dump_project(project, with_documentation=with_documentation), headers=headers
            )

        return "/projects/<project_id:ulid>", ["GET"], _get_one

    def get_one_by_namespace_slug(self) -> BlueprintFactoryResponse:
        """Get a specific project by namespace/slug."""

        @authenticate(self.authenticator)
        @extract_if_none_match
        @validate_query(query=apispec.NamespacesNamespaceProjectsSlugGetParametersQuery)
        async def _get_one_by_namespace_slug(
            _: Request,
            user: base_models.APIUser,
            namespace: str,
            slug: Slug,
            etag: str | None,
            query: apispec.NamespacesNamespaceProjectsSlugGetParametersQuery,
        ) -> JSONResponse | HTTPResponse:
            with_documentation = query.with_documentation is True
            project = await self.project_repo.get_project_by_namespace_slug(
                user=user, namespace=namespace, slug=slug, with_documentation=with_documentation
            )

            if project.etag is not None and project.etag == etag:
                return HTTPResponse(status=304)

            headers = {"ETag": project.etag} if project.etag is not None else None
            return validated_json(
                apispec.Project,
                self._dump_project(project, with_documentation=with_documentation),
                headers=headers,
            )

        return "/namespaces/<namespace>/projects/<slug:renku_slug>", ["GET"], _get_one_by_namespace_slug

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific project."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete(_: Request, user: base_models.APIUser, project_id: ULID) -> HTTPResponse:
            await self.project_repo.delete_project(user=user, project_id=project_id)
            return HTTPResponse(status=204)

        return "/projects/<project_id:ulid>", ["DELETE"], _delete

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update a specific project."""

        @authenticate(self.authenticator)
        @only_authenticated
        @if_match_required
        @validate(json=apispec.ProjectPatch)
        async def _patch(
            _: Request, user: base_models.APIUser, project_id: ULID, body: apispec.ProjectPatch, etag: str
        ) -> JSONResponse:
            project_patch = validate_project_patch(body)
            project_update = await self.project_repo.update_project(
                user=user, project_id=project_id, etag=etag, patch=project_patch
            )

            if not isinstance(project_update, project_models.ProjectUpdate):
                raise errors.ProgrammingError(
                    message="Expected the result of a project update to be ProjectUpdate but instead "
                    f"got {type(project_update)}"
                )
            if len(project_update.new.repositories) > len(project_update.old.repositories):
                await self.metrics.code_repo_linked_to_project(user)

            updated_project = project_update.new
            return validated_json(apispec.Project, self._dump_project(updated_project))

        return "/projects/<project_id:ulid>", ["PATCH"], _patch

    def get_all_members(self) -> BlueprintFactoryResponse:
        """List all project members."""

        @authenticate(self.authenticator)
        async def _get_all_members(_: Request, user: base_models.APIUser, project_id: ULID) -> JSONResponse:
            members = await self.project_member_repo.get_members(user, project_id)

            users = []

            for member in members:
                user_id = member.user_id
                user_info = await self.user_repo.get_user(id=user_id)
                if not user_info:
                    raise errors.MissingResourceError(message=f"The user with ID {user_id} cannot be found.")
                namespace_info = user_info.namespace

                user_with_id = apispec.ProjectMemberResponse(
                    id=user_id,
                    namespace=namespace_info.path.first.value,
                    first_name=user_info.first_name,
                    last_name=user_info.last_name,
                    role=apispec.Role(member.role.value),
                ).model_dump(exclude_none=True, mode="json")
                users.append(user_with_id)

            return validated_json(apispec.ProjectMemberListResponse, users)

        return "/projects/<project_id:ulid>/members", ["GET"], _get_all_members

    def update_members(self) -> BlueprintFactoryResponse:
        """Update or add project members."""

        @authenticate(self.authenticator)
        @validate_body_root_model(json=apispec.ProjectMemberListPatchRequest)
        async def _update_members(
            _: Request, user: base_models.APIUser, project_id: ULID, body: apispec.ProjectMemberListPatchRequest
        ) -> HTTPResponse:
            members = [Member(Role(i.role.value), i.id, project_id) for i in body.root]
            result = await self.project_member_repo.update_members(user, project_id, members)

            if any(c.change == Change.ADD for c in result):
                await self.metrics.project_member_added(user)

            return HTTPResponse(status=200)

        return "/projects/<project_id:ulid>/members", ["PATCH"], _update_members

    def delete_member(self) -> BlueprintFactoryResponse:
        """Delete a specific project."""

        @authenticate(self.authenticator)
        @validate_path_user_id
        async def _delete_member(
            _: Request, user: base_models.APIUser, project_id: ULID, member_id: str
        ) -> HTTPResponse:
            await self.project_member_repo.delete_members(user, project_id, [member_id])
            return HTTPResponse(status=204)

        return "/projects/<project_id:ulid>/members/<member_id>", ["DELETE"], _delete_member

    def get_permissions(self) -> BlueprintFactoryResponse:
        """Get the permissions of the current user on the project."""

        @authenticate(self.authenticator)
        async def _get_permissions(_: Request, user: base_models.APIUser, project_id: ULID) -> JSONResponse:
            permissions = await self.project_repo.get_project_permissions(user=user, project_id=project_id)
            return validated_json(apispec.ProjectPermissions, permissions)

        return "/projects/<project_id:ulid>/permissions", ["GET"], _get_permissions

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

    @staticmethod
    def _dump_project_migration(project_migration: project_models.ProjectMigrationInfo) -> dict[str, Any]:
        """Dumps a project migration for API responses."""
        result = dict(
            project_id=project_migration.project_id,
            v1_id=project_migration.v1_id,
            launcher_id=project_migration.launcher_id,
        )
        return result


@dataclass(kw_only=True)
class ProjectSessionSecretBP(CustomBlueprint):
    """Handlers for manipulating session secrets in a project."""

    session_secret_repo: ProjectSessionSecretRepository
    authenticator: base_models.Authenticator

    def get_session_secret_slots(self) -> BlueprintFactoryResponse:
        """Get the session secret slots of a project."""

        @authenticate(self.authenticator)
        async def _get_session_secret_slots(_: Request, user: base_models.APIUser, project_id: ULID) -> JSONResponse:
            secret_slots = await self.session_secret_repo.get_all_session_secret_slots_from_project(
                user=user, project_id=project_id
            )
            return validated_json(apispec.SessionSecretSlotList, secret_slots)

        return "/projects/<project_id:ulid>/session_secret_slots", ["GET"], _get_session_secret_slots

    def post_session_secret_slot(self) -> BlueprintFactoryResponse:
        """Create a new session secret slot on a project."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.SessionSecretSlotPost)
        async def _post_session_secret_slot(
            _: Request, user: base_models.APIUser, body: apispec.SessionSecretSlotPost
        ) -> JSONResponse:
            unsaved_secret_slot = validate_unsaved_session_secret_slot(body)
            secret_slot = await self.session_secret_repo.insert_session_secret_slot(
                user=user, secret_slot=unsaved_secret_slot
            )
            return validated_json(apispec.SessionSecretSlot, secret_slot, status=201)

        return "/session_secret_slots", ["POST"], _post_session_secret_slot

    def get_session_secret_slot(self) -> BlueprintFactoryResponse:
        """Get the details of a session secret slot."""

        @authenticate(self.authenticator)
        @extract_if_none_match
        async def _get_session_secret_slot(
            _: Request, user: base_models.APIUser, slot_id: ULID, etag: str | None
        ) -> HTTPResponse:
            secret_slot = await self.session_secret_repo.get_session_secret_slot(user=user, slot_id=slot_id)

            if secret_slot.etag == etag:
                return HTTPResponse(status=304)

            return validated_json(apispec.SessionSecretSlot, secret_slot)

        return "/session_secret_slots/<slot_id:ulid>", ["GET"], _get_session_secret_slot

    def patch_session_secret_slot(self) -> BlueprintFactoryResponse:
        """Update specific fields of an existing session secret slot."""

        @authenticate(self.authenticator)
        @only_authenticated
        @if_match_required
        @validate(json=apispec.SessionSecretSlotPatch)
        async def _patch_session_secret_slot(
            _: Request,
            user: base_models.APIUser,
            slot_id: ULID,
            body: apispec.SessionSecretSlotPatch,
            etag: str,
        ) -> JSONResponse:
            secret_slot_patch = validate_session_secret_slot_patch(body)
            secret_slot = await self.session_secret_repo.update_session_secret_slot(
                user=user, slot_id=slot_id, patch=secret_slot_patch, etag=etag
            )
            return validated_json(apispec.SessionSecretSlot, secret_slot)

        return "/session_secret_slots/<slot_id:ulid>", ["PATCH"], _patch_session_secret_slot

    def delete_session_secret_slot(self) -> BlueprintFactoryResponse:
        """Remove a session secret slot."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete_session_secret_slot(_: Request, user: base_models.APIUser, slot_id: ULID) -> HTTPResponse:
            await self.session_secret_repo.delete_session_secret_slot(user=user, slot_id=slot_id)
            return HTTPResponse(status=204)

        return "/session_secret_slots/<slot_id:ulid>", ["DELETE"], _delete_session_secret_slot

    def get_session_secrets(self) -> BlueprintFactoryResponse:
        """Get the current user's secrets of a project."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _get_session_secrets(_: Request, user: base_models.APIUser, project_id: ULID) -> JSONResponse:
            secrets = await self.session_secret_repo.get_all_session_secrets_from_project(
                user=user, project_id=project_id
            )
            return validated_json(apispec.SessionSecretList, secrets)

        return "/projects/<project_id:ulid>/session_secrets", ["GET"], _get_session_secrets

    def patch_session_secrets(self) -> BlueprintFactoryResponse:
        """Save user secrets for a project."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate_body_root_model(json=apispec.SessionSecretPatchList)
        async def _patch_session_secrets(
            _: Request, user: base_models.APIUser, project_id: ULID, body: apispec.SessionSecretPatchList
        ) -> JSONResponse:
            secrets_patch = validate_session_secrets_patch(body)
            secrets = await self.session_secret_repo.patch_session_secrets(
                user=user, project_id=project_id, secrets=secrets_patch
            )
            return validated_json(apispec.SessionSecretList, secrets)

        return "/projects/<project_id:ulid>/session_secrets", ["PATCH"], _patch_session_secrets

    def delete_session_secrets(self) -> BlueprintFactoryResponse:
        """Remove all user secrets for a project."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete_session_secrets(_: Request, user: base_models.APIUser, project_id: ULID) -> HTTPResponse:
            await self.session_secret_repo.delete_session_secrets(user=user, project_id=project_id)
            return HTTPResponse(status=204)

        return "/projects/<project_id:ulid>/session_secrets", ["DELETE"], _delete_session_secrets
