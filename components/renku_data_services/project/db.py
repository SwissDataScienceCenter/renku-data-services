"""Adapters for project database classes."""

from __future__ import annotations

import functools
import random
import string
from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Concatenate, ParamSpec, TypeVar

from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import ColumnElement, Select, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer
from sqlalchemy.sql.functions import coalesce
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.authz.authz import Authz, AuthzOperation, ResourceType
from renku_data_services.authz.models import CheckPermissionItem, Member, MembershipChange, Scope, Visibility
from renku_data_services.base_api.pagination import PaginationRequest
from renku_data_services.base_models import RESET, ProjectPath, ProjectSlug
from renku_data_services.base_models.core import Slug
from renku_data_services.data_connectors import orm as dc_schemas
from renku_data_services.namespace import orm as ns_schemas
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.project import apispec as project_apispec
from renku_data_services.project import constants, models
from renku_data_services.project import orm as schemas
from renku_data_services.search.db import SearchUpdatesRepo
from renku_data_services.search.decorators import update_search_document
from renku_data_services.secrets import orm as secrets_schemas
from renku_data_services.secrets.models import SecretKind
from renku_data_services.session import apispec as session_apispec
from renku_data_services.session.core import (
    validate_unsaved_session_launcher,
)
from renku_data_services.session.db import SessionRepository
from renku_data_services.storage import orm as storage_schemas
from renku_data_services.users.db import UserRepo
from renku_data_services.users.orm import UserORM
from renku_data_services.utils.core import with_db_transaction


class ProjectRepository:
    """Repository for projects."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        group_repo: GroupRepository,
        search_updates_repo: SearchUpdatesRepo,
        authz: Authz,
    ) -> None:
        self.session_maker = session_maker
        self.group_repo: GroupRepository = group_repo
        self.search_updates_repo: SearchUpdatesRepo = search_updates_repo
        self.authz = authz

    async def get_projects(
        self,
        user: base_models.APIUser,
        pagination: PaginationRequest,
        namespace: str | None = None,
        direct_member: bool = False,
    ) -> tuple[list[models.Project], int]:
        """Get all projects from the database."""
        if direct_member:
            project_ids = await self.authz.resources_with_direct_membership(user, ResourceType.project)
        else:
            project_ids = await self.authz.resources_with_permission(user, user.id, ResourceType.project, Scope.READ)

        async with self.session_maker() as session:
            stmt = select(schemas.ProjectORM)
            stmt = stmt.where(schemas.ProjectORM.id.in_(project_ids))
            if namespace:
                stmt = _filter_projects_by_namespace_slug(stmt, namespace)

            stmt = stmt.order_by(coalesce(schemas.ProjectORM.updated_at, schemas.ProjectORM.creation_date).desc())

            stmt = stmt.limit(pagination.per_page).offset(pagination.offset)

            stmt_count = (
                select(func.count()).select_from(schemas.ProjectORM).where(schemas.ProjectORM.id.in_(project_ids))
            )
            if namespace:
                stmt_count = _filter_projects_by_namespace_slug(stmt_count, namespace)
            results = await session.scalars(stmt), await session.scalar(stmt_count)
            projects_orm = results[0].all()
            total_elements = results[1] or 0
            return [p.dump() for p in projects_orm], total_elements

    async def get_all_projects(self, requested_by: base_models.APIUser) -> AsyncGenerator[models.Project, None]:
        """Get all projects from the database when reprovisioning."""
        if not requested_by.is_admin:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session:
            projects = await session.stream_scalars(select(schemas.ProjectORM))
            async for project in projects:
                yield project.dump()

    async def get_project(
        self, user: base_models.APIUser, project_id: ULID, with_documentation: bool = False
    ) -> models.Project:
        """Get one project from the database."""
        authorized = await self.authz.has_permission(user, ResourceType.project, project_id, Scope.READ)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        async with self.session_maker() as session:
            stmt = select(schemas.ProjectORM).where(schemas.ProjectORM.id == project_id)
            if with_documentation:
                stmt = stmt.options(undefer(schemas.ProjectORM.documentation))
            result = await session.execute(stmt)
            project_orm = result.scalars().first()

            if project_orm is None:
                raise errors.MissingResourceError(message=f"Project with id '{project_id}' does not exist.")

            return project_orm.dump(with_documentation=with_documentation)

    async def get_all_copied_projects(
        self, user: base_models.APIUser, project_id: ULID, only_writable: bool
    ) -> list[models.Project]:
        """Get all projects that are copied from the specified project."""
        authorized = await self.authz.has_permission(user, ResourceType.project, project_id, Scope.READ)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        async with self.session_maker() as session:
            # NOTE: Show only those projects that user has access to
            scope = Scope.WRITE if only_writable else Scope.NON_PUBLIC_READ
            project_ids = await self.authz.resources_with_permission(user, user.id, ResourceType.project, scope=scope)

            cond: ColumnElement[bool] = schemas.ProjectORM.id.in_(project_ids)
            if scope == Scope.NON_PUBLIC_READ:
                cond = or_(cond, schemas.ProjectORM.visibility == Visibility.PUBLIC.value)

            stmt = select(schemas.ProjectORM).where(schemas.ProjectORM.template_id == project_id).where(cond)
            result = await session.execute(stmt)
            project_orms = result.scalars().all()

            return [p.dump() for p in project_orms]

    async def get_project_by_namespace_slug(
        self, user: base_models.APIUser, namespace: str, slug: Slug, with_documentation: bool = False
    ) -> models.Project:
        """Get one project from the database."""
        async with self.session_maker() as session:
            stmt = select(schemas.ProjectORM)
            stmt = _filter_projects_by_namespace_slug(stmt, namespace)
            stmt = stmt.where(schemas.ProjectORM.slug.has(ns_schemas.EntitySlugORM.slug == slug.value))
            if with_documentation:
                stmt = stmt.options(undefer(schemas.ProjectORM.documentation))
            result = await session.scalars(stmt)
            project_orm = result.first()

            if project_orm is None:
                old_project_stmt_old_ns_current_slug = (
                    select(schemas.ProjectORM.id)
                    .where(ns_schemas.NamespaceOldORM.slug == namespace.lower())
                    .where(ns_schemas.NamespaceOldORM.latest_slug_id == ns_schemas.NamespaceORM.id)
                    .where(ns_schemas.EntitySlugORM.namespace_id == ns_schemas.NamespaceORM.id)
                    .where(schemas.ProjectORM.id == ns_schemas.EntitySlugORM.project_id)
                    .where(schemas.ProjectORM.slug.has(ns_schemas.EntitySlugORM.slug == slug.value))
                )
                old_project_stmt_current_ns_old_slug = (
                    select(schemas.ProjectORM.id)
                    .where(ns_schemas.NamespaceORM.slug == namespace.lower())
                    .where(ns_schemas.EntitySlugORM.namespace_id == ns_schemas.NamespaceORM.id)
                    .where(schemas.ProjectORM.id == ns_schemas.EntitySlugORM.project_id)
                    .where(ns_schemas.EntitySlugOldORM.slug == slug.value)
                    .where(ns_schemas.EntitySlugOldORM.latest_slug_id == ns_schemas.EntitySlugORM.id)
                )
                old_project_stmt_old_ns_old_slug = (
                    select(schemas.ProjectORM.id)
                    .where(ns_schemas.NamespaceOldORM.slug == namespace.lower())
                    .where(ns_schemas.NamespaceOldORM.latest_slug_id == ns_schemas.NamespaceORM.id)
                    .where(ns_schemas.EntitySlugORM.namespace_id == ns_schemas.NamespaceORM.id)
                    .where(schemas.ProjectORM.id == ns_schemas.EntitySlugORM.project_id)
                    .where(ns_schemas.EntitySlugOldORM.slug == slug.value)
                    .where(ns_schemas.EntitySlugOldORM.latest_slug_id == ns_schemas.EntitySlugORM.id)
                )
                old_project_stmt = old_project_stmt_old_ns_current_slug.union(
                    old_project_stmt_current_ns_old_slug, old_project_stmt_old_ns_old_slug
                )
                result_old = await session.scalars(old_project_stmt)
                result_old_id = result_old.first()
                if result_old_id is not None:
                    stmt = select(schemas.ProjectORM).where(schemas.ProjectORM.id == result_old_id)
                    if with_documentation:
                        stmt = stmt.options(undefer(schemas.ProjectORM.documentation))
                    project_orm = (await session.scalars(stmt)).first()

            not_found_msg = (
                f"Project with identifier '{namespace}/{slug}' does not exist or you do not have access to it."
            )

            if project_orm is None:
                raise errors.MissingResourceError(message=not_found_msg)

            authorized = await self.authz.has_permission(
                user=user,
                resource_type=ResourceType.project,
                resource_id=project_orm.id,
                scope=Scope.READ,
            )
            if not authorized:
                raise errors.MissingResourceError(message=not_found_msg)

            return project_orm.dump(with_documentation=with_documentation)

    @with_db_transaction
    @Authz.authz_change(AuthzOperation.create, ResourceType.project)
    @update_search_document
    async def insert_project(
        self,
        user: base_models.APIUser,
        project: models.UnsavedProject,
        *,
        session: AsyncSession | None = None,
    ) -> models.Project:
        """Insert a new project entry."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required")
        ns = await session.scalar(
            select(ns_schemas.NamespaceORM).where(ns_schemas.NamespaceORM.slug == project.namespace.lower())
        )
        if not ns:
            raise errors.MissingResourceError(
                message=f"The project cannot be created because the namespace {project.namespace} does not exist"
            )
        if not ns.group_id and not ns.user_id:
            raise errors.ProgrammingError(message="Found a namespace that has no group or user associated with it.")

        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        resource_type, resource_id = (
            (ResourceType.group, ns.group_id) if ns.group and ns.group_id else (ResourceType.user_namespace, ns.id)
        )
        has_permission = await self.authz.has_permission(user, resource_type, resource_id, Scope.WRITE)
        if not has_permission:
            raise errors.ForbiddenError(
                message=f"The project cannot be created because you do not have sufficient permissions with the namespace {project.namespace}"  # noqa: E501
            )

        slug = project.slug or base_models.Slug.from_name(project.name).value

        existing_slug = await session.scalar(
            select(ns_schemas.EntitySlugORM)
            .where(ns_schemas.EntitySlugORM.namespace_id == ns.id)
            .where(ns_schemas.EntitySlugORM.slug == slug)
            .where(ns_schemas.EntitySlugORM.data_connector_id.is_(None))
            .where(ns_schemas.EntitySlugORM.project_id.is_not(None)),
        )
        if existing_slug is not None:
            raise errors.ConflictError(message=f"An entity with the slug '{ns.slug}/{slug}' already exists.")

        repositories = [schemas.ProjectRepositoryORM(url) for url in (project.repositories or [])]
        project_orm = schemas.ProjectORM(
            name=project.name,
            visibility=(
                project_apispec.Visibility(project.visibility)
                if isinstance(project.visibility, str)
                else project_apispec.Visibility(project.visibility.value)
            ),
            created_by_id=user.id,
            description=project.description,
            repositories=repositories,
            creation_date=datetime.now(UTC).replace(microsecond=0),
            keywords=project.keywords,
            documentation=project.documentation,
            template_id=project.template_id,
            secrets_mount_directory=project.secrets_mount_directory or constants.DEFAULT_SESSION_SECRETS_MOUNT_DIR,
        )
        project_slug = ns_schemas.EntitySlugORM.create_project_slug(slug, project_id=project_orm.id, namespace_id=ns.id)

        session.add(project_orm)
        session.add(project_slug)
        await session.flush()
        await session.refresh(project_orm)
        return project_orm.dump()

    @with_db_transaction
    @Authz.authz_change(AuthzOperation.update, ResourceType.project)
    @update_search_document
    async def update_project(
        self,
        user: base_models.APIUser,
        project_id: ULID,
        patch: models.ProjectPatch,
        etag: str | None = None,
        *,
        session: AsyncSession | None = None,
    ) -> models.ProjectUpdate:
        """Update a project entry."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required")
        result = await session.scalars(select(schemas.ProjectORM).where(schemas.ProjectORM.id == project_id))
        project = result.one_or_none()
        if project is None:
            raise errors.MissingResourceError(message=f"The project with id '{project_id}' cannot be found")
        old_project = project.dump()

        required_scope = Scope.WRITE
        if patch.visibility is not None and patch.visibility != old_project.visibility:
            # NOTE: changing the visibility requires the user to be owner which means they should have DELETE permission
            required_scope = Scope.DELETE
        if patch.namespace is not None and patch.namespace != old_project.namespace.path.first.value:
            # NOTE: changing the namespace requires the user to be owner which means they should have DELETE permission
            required_scope = Scope.DELETE
        if patch.slug is not None and patch.slug != old_project.slug:
            # NOTE: changing the slug requires the user to be owner which means they should have DELETE permission
            required_scope = Scope.DELETE
        authorized = await self.authz.has_permission(user, ResourceType.project, project_id, required_scope)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        current_etag = old_project.etag
        if etag is not None and current_etag != etag:
            raise errors.ConflictError(message=f"Current ETag is {current_etag}, not {etag}.")

        if patch.name is not None:
            project.name = patch.name
        new_path: ProjectPath | None = None
        if patch.namespace is not None and patch.namespace != old_project.namespace.path.first.value:
            new_path = ProjectPath.from_strings(patch.namespace, old_project.slug)
        if patch.slug is not None and patch.slug != old_project.slug:
            if new_path:
                new_path = new_path.parent() / ProjectSlug(patch.slug)
            else:
                new_path = old_project.path.parent() / ProjectSlug(patch.slug)
        if new_path:
            await self.group_repo.move_project(user, old_project, new_path, session)
            # Trigger update for ``updated_at`` column
            await session.execute(update(schemas.ProjectORM).where(schemas.ProjectORM.id == project_id).values())
        if patch.visibility is not None:
            visibility_orm = (
                project_apispec.Visibility(patch.visibility)
                if isinstance(patch.visibility, str)
                else project_apispec.Visibility(patch.visibility.value)
            )
            project.visibility = visibility_orm
        if patch.repositories is not None:
            project.repositories = [
                schemas.ProjectRepositoryORM(url=r, project_id=project.id, project=project) for r in patch.repositories
            ]
            # Trigger update for ``updated_at`` column
            await session.execute(update(schemas.ProjectORM).where(schemas.ProjectORM.id == project_id).values())
        if patch.description is not None:
            project.description = patch.description if patch.description else None
        if patch.keywords is not None:
            project.keywords = patch.keywords if patch.keywords else None
        if patch.documentation is not None:
            project.documentation = patch.documentation
        if patch.template_id is not None:
            project.template_id = None
        if patch.is_template is not None:
            project.is_template = patch.is_template
        if patch.secrets_mount_directory is not None and patch.secrets_mount_directory is RESET:
            project.secrets_mount_directory = constants.DEFAULT_SESSION_SECRETS_MOUNT_DIR
        elif patch.secrets_mount_directory is not None and isinstance(patch.secrets_mount_directory, PurePosixPath):
            project.secrets_mount_directory = patch.secrets_mount_directory

        await session.flush()
        await session.refresh(project)

        return models.ProjectUpdate(
            old=old_project,
            new=project.dump(),  # NOTE: Triggers validation before the transaction saves data
        )

    @with_db_transaction
    @Authz.authz_change(AuthzOperation.delete, ResourceType.project)
    @update_search_document
    async def delete_project(
        self, user: base_models.APIUser, project_id: ULID, *, session: AsyncSession | None = None
    ) -> models.DeletedProject | None:
        """Delete a project."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required")
        authorized = await self.authz.has_permission(user, ResourceType.project, project_id, Scope.DELETE)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        result = await session.execute(select(schemas.ProjectORM).where(schemas.ProjectORM.id == project_id))
        project = result.scalar_one_or_none()

        if project is None:
            return None

        dcs = await session.execute(
            select(ns_schemas.EntitySlugORM.data_connector_id)
            .where(ns_schemas.EntitySlugORM.project_id == project_id)
            .where(ns_schemas.EntitySlugORM.data_connector_id.is_not(None))
        )
        dcs = [e for e in dcs.scalars().all() if e]

        await session.execute(delete(schemas.ProjectORM).where(schemas.ProjectORM.id == project_id))

        await session.execute(
            delete(storage_schemas.CloudStorageORM).where(storage_schemas.CloudStorageORM.project_id == str(project_id))
        )

        if dcs != []:
            await session.execute(delete(dc_schemas.DataConnectorORM).where(dc_schemas.DataConnectorORM.id.in_(dcs)))

        return models.DeletedProject(id=project.id, data_connectors=dcs)

    async def get_project_permissions(self, user: base_models.APIUser, project_id: ULID) -> models.ProjectPermissions:
        """Get the permissions of the user on a given project."""
        # Get the project first, it will check if the user can view it.
        await self.get_project(user=user, project_id=project_id)

        scopes = [Scope.WRITE, Scope.DELETE, Scope.CHANGE_MEMBERSHIP]
        items = [
            CheckPermissionItem(resource_type=ResourceType.project, resource_id=project_id, scope=scope)
            for scope in scopes
        ]
        responses = await self.authz.has_permissions(user=user, items=items)
        permissions = models.ProjectPermissions(write=False, delete=False, change_membership=False)
        for item, has_permission in responses:
            if not has_permission:
                continue
            match item.scope:
                case Scope.WRITE:
                    permissions.write = True
                case Scope.DELETE:
                    permissions.delete = True
                case Scope.CHANGE_MEMBERSHIP:
                    permissions.change_membership = True
        return permissions


_P = ParamSpec("_P")
_T = TypeVar("_T")


def _filter_projects_by_namespace_slug(statement: Select[tuple[_T]], namespace: str) -> Select[tuple[_T]]:
    """Filters a select query on projects to a given namespace."""
    return statement.where(
        schemas.ProjectORM.slug.has(
            ns_schemas.EntitySlugORM.namespace.has(
                ns_schemas.NamespaceORM.slug == namespace.lower(),
            )
        )
    )


def _project_exists(
    f: Callable[Concatenate[ProjectMemberRepository, base_models.APIUser, ULID, _P], Awaitable[_T]],
) -> Callable[Concatenate[ProjectMemberRepository, base_models.APIUser, ULID, _P], Awaitable[_T]]:
    """Checks if the project exists when adding or modifying project members."""

    @functools.wraps(f)
    async def decorated_func(
        self: ProjectMemberRepository,
        user: base_models.APIUser,
        project_id: ULID,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> _T:
        session = kwargs.get("session")
        if not isinstance(session, AsyncSession):
            raise errors.ProgrammingError(
                message="The decorator that checks if a project exists requires a database session in the "
                f"keyword arguments, but instead it got {type(session)}"
            )
        stmt = select(schemas.ProjectORM.id).where(schemas.ProjectORM.id == project_id)
        res = await session.scalar(stmt)
        if not res:
            raise errors.MissingResourceError(
                message=f"Project with ID {project_id} does not exist or you do not have access to it."
            )
        return await f(self, user, project_id, *args, **kwargs)

    return decorated_func


class ProjectMemberRepository:
    """Repository for project members."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        authz: Authz,
    ) -> None:
        self.session_maker = session_maker
        self.authz = authz

    @with_db_transaction
    @_project_exists
    async def get_members(
        self, user: base_models.APIUser, project_id: ULID, *, session: AsyncSession | None = None
    ) -> list[Member]:
        """Get all members of a project."""
        members = await self.authz.members(user, ResourceType.project, project_id)
        members = [member for member in members if member.user_id and member.user_id != "*"]
        return members

    @with_db_transaction
    @_project_exists
    async def update_members(
        self,
        user: base_models.APIUser,
        project_id: ULID,
        members: list[Member],
        *,
        session: AsyncSession | None = None,
    ) -> list[MembershipChange]:
        """Update project's members."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required")
        if len(members) == 0:
            raise errors.ValidationError(message="Please request at least 1 member to be added to the project")

        requested_member_ids = [member.user_id for member in members]
        requested_member_ids_set = set(requested_member_ids)
        stmt = select(UserORM.keycloak_id).where(UserORM.keycloak_id.in_(requested_member_ids))
        res = await session.scalars(stmt)
        existing_member_ids = set(res)
        if len(existing_member_ids) != len(requested_member_ids_set):
            raise errors.MissingResourceError(
                message="You are trying to add users to the project, but the users with ids "
                f"{requested_member_ids_set.difference(existing_member_ids)} cannot be found"
            )

        output = await self.authz.upsert_project_members(user, ResourceType.project, project_id, members)
        return output

    @with_db_transaction
    @_project_exists
    async def delete_members(
        self, user: base_models.APIUser, project_id: ULID, user_ids: list[str], *, session: AsyncSession | None = None
    ) -> list[MembershipChange]:
        """Delete members from a project."""
        if len(user_ids) == 0:
            raise errors.ValidationError(message="Please request at least 1 member to be removed from the project")

        members = await self.authz.remove_project_members(user, ResourceType.project, project_id, user_ids)
        return members


class ProjectSessionSecretRepository:
    """Repository for session secrets."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        authz: Authz,
        user_repo: UserRepo,
        secret_service_public_key: rsa.RSAPublicKey,
    ) -> None:
        self.session_maker = session_maker
        self.authz = authz
        self.user_repo = user_repo
        self.secret_service_public_key = secret_service_public_key

    async def get_all_session_secret_slots_from_project(
        self,
        user: base_models.APIUser,
        project_id: ULID,
    ) -> list[models.SessionSecretSlot]:
        """Get all session secret slots from a project."""
        # Check that the user is allowed to access the project
        authorized = await self.authz.has_permission(user, ResourceType.project, project_id, Scope.READ)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )
        async with self.session_maker() as session:
            result = await session.scalars(
                select(schemas.SessionSecretSlotORM)
                .where(schemas.SessionSecretSlotORM.project_id == project_id)
                .order_by(schemas.SessionSecretSlotORM.id.desc())
            )
            secret_slots = result.all()
            return [s.dump() for s in secret_slots]

    async def get_session_secret_slot(
        self,
        user: base_models.APIUser,
        slot_id: ULID,
    ) -> models.SessionSecretSlot:
        """Get one session secret slot from the database."""
        async with self.session_maker() as session, session.begin():
            result = await session.scalars(
                select(schemas.SessionSecretSlotORM).where(schemas.SessionSecretSlotORM.id == slot_id)
            )
            secret_slot = result.one_or_none()

            authorized = (
                await self.authz.has_permission(user, ResourceType.project, secret_slot.project_id, Scope.READ)
                if secret_slot is not None
                else False
            )
            if not authorized or secret_slot is None:
                raise errors.MissingResourceError(
                    message=f"Session secret slot with id '{slot_id}' does not exist or you do not have access to it."
                )

            return secret_slot.dump()

    async def insert_session_secret_slot(
        self, user: base_models.APIUser, secret_slot: models.UnsavedSessionSecretSlot
    ) -> models.SessionSecretSlot:
        """Insert a new session secret slot entry."""
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        # Check that the user is allowed to access the project
        authorized = await self.authz.has_permission(user, ResourceType.project, secret_slot.project_id, Scope.WRITE)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{secret_slot.project_id}' does not exist or you do not have access to it."
            )

        async with self.session_maker() as session, session.begin():
            existing_secret_slot = await session.scalar(
                select(schemas.SessionSecretSlotORM)
                .where(schemas.SessionSecretSlotORM.project_id == secret_slot.project_id)
                .where(schemas.SessionSecretSlotORM.filename == secret_slot.filename)
            )
            if existing_secret_slot is not None:
                raise errors.ConflictError(
                    message=f"A session secret slot with the filename '{secret_slot.filename}' already exists."
                )

            secret_slot_orm = schemas.SessionSecretSlotORM(
                project_id=secret_slot.project_id,
                name=secret_slot.name or secret_slot.filename,
                description=secret_slot.description if secret_slot.description else None,
                filename=secret_slot.filename,
                created_by_id=user.id,
            )

            session.add(secret_slot_orm)
            await session.flush()
            await session.refresh(secret_slot_orm)

            return secret_slot_orm.dump()

    async def update_session_secret_slot(
        self, user: base_models.APIUser, slot_id: ULID, patch: models.SessionSecretSlotPatch, etag: str
    ) -> models.SessionSecretSlot:
        """Update a session secret slot entry."""
        not_found_msg = f"Session secret slot with id '{slot_id}' does not exist or you do not have access to it."

        async with self.session_maker() as session, session.begin():
            result = await session.scalars(
                select(schemas.SessionSecretSlotORM).where(schemas.SessionSecretSlotORM.id == slot_id)
            )
            secret_slot = result.one_or_none()
            if secret_slot is None:
                raise errors.MissingResourceError(message=not_found_msg)

            authorized = await self.authz.has_permission(
                user, ResourceType.project, secret_slot.project_id, Scope.WRITE
            )
            if not authorized:
                raise errors.MissingResourceError(message=not_found_msg)

            current_etag = secret_slot.dump().etag
            if current_etag != etag:
                raise errors.ConflictError(message=f"Current ETag is {current_etag}, not {etag}.")

            if patch.name is not None:
                secret_slot.name = patch.name
            if patch.description is not None:
                secret_slot.description = patch.description if patch.description else None
            if patch.filename is not None and patch.filename != secret_slot.filename:
                existing_secret_slot = await session.scalar(
                    select(schemas.SessionSecretSlotORM)
                    .where(schemas.SessionSecretSlotORM.project_id == secret_slot.project_id)
                    .where(schemas.SessionSecretSlotORM.filename == patch.filename)
                )
                if existing_secret_slot is not None:
                    raise errors.ConflictError(
                        message=f"A session secret slot with the filename '{patch.filename}' already exists."
                    )
                secret_slot.filename = patch.filename

            await session.flush()
            await session.refresh(secret_slot)

            return secret_slot.dump()

    async def delete_session_secret_slot(
        self,
        user: base_models.APIUser,
        slot_id: ULID,
    ) -> None:
        """Delete a session secret slot."""
        async with self.session_maker() as session, session.begin():
            result = await session.scalars(
                select(schemas.SessionSecretSlotORM).where(schemas.SessionSecretSlotORM.id == slot_id)
            )
            secret_slot = result.one_or_none()
            if secret_slot is None:
                return None

            authorized = await self.authz.has_permission(
                user, ResourceType.project, secret_slot.project_id, Scope.WRITE
            )
            if not authorized:
                raise errors.MissingResourceError(
                    message=f"Session secret slot with id '{slot_id}' does not exist or you do not have access to it."
                )

            await session.delete(secret_slot)

    async def get_all_session_secrets_from_project(
        self,
        user: base_models.APIUser,
        project_id: ULID,
    ) -> list[models.SessionSecret]:
        """Get all session secrets from a project."""
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        # Check that the user is allowed to access the project
        authorized = await self.authz.has_permission(user, ResourceType.project, project_id, Scope.READ)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        async with self.session_maker() as session:
            result = await session.scalars(
                select(schemas.SessionSecretORM)
                .where(schemas.SessionSecretORM.user_id == user.id)
                .where(schemas.SessionSecretORM.secret_slot_id == schemas.SessionSecretSlotORM.id)
                .where(schemas.SessionSecretSlotORM.project_id == project_id)
                .order_by(schemas.SessionSecretORM.id.desc())
            )
            secrets = result.all()

            return [s.dump() for s in secrets]

    async def patch_session_secrets(
        self,
        user: base_models.APIUser,
        project_id: ULID,
        secrets: list[models.SessionSecretPatchExistingSecret | models.SessionSecretPatchSecretValue],
    ) -> list[models.SessionSecret]:
        """Create, update or remove session secrets."""
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        # Check that the user is allowed to access the project
        authorized = await self.authz.has_permission(user, ResourceType.project, project_id, Scope.READ)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        secrets_as_dict = {s.secret_slot_id: s for s in secrets}

        async with self.session_maker() as session, session.begin():
            result = await session.scalars(
                select(schemas.SessionSecretORM)
                .where(schemas.SessionSecretORM.user_id == user.id)
                .where(schemas.SessionSecretORM.secret_slot_id == schemas.SessionSecretSlotORM.id)
                .where(schemas.SessionSecretSlotORM.project_id == project_id)
            )
            existing_secrets = result.all()
            existing_secrets_as_dict = {s.secret_slot_id: s for s in existing_secrets}

            result_slots = await session.scalars(
                select(schemas.SessionSecretSlotORM).where(schemas.SessionSecretSlotORM.project_id == project_id)
            )
            secret_slots = result_slots.all()
            secret_slots_as_dict = {s.id: s for s in secret_slots}

            all_secrets = []

            for slot_id, secret_update in secrets_as_dict.items():
                secret_slot = secret_slots_as_dict.get(slot_id)
                if secret_slot is None:
                    raise errors.ValidationError(
                        message=f"Session secret slot with id '{slot_id}' does not exist or you do not have access to it."  # noqa: E501
                    )

                if isinstance(secret_update, models.SessionSecretPatchExistingSecret):
                    # Update the secret_id
                    if session_launcher_secret_orm := existing_secrets_as_dict.get(slot_id):
                        session_launcher_secret_orm.secret_id = secret_update.secret_id
                    else:
                        session_launcher_secret_orm = schemas.SessionSecretORM(
                            secret_slot_id=secret_update.secret_slot_id,
                            secret_id=secret_update.secret_id,
                            user_id=user.id,
                        )
                        session.add(session_launcher_secret_orm)
                        await session.flush()
                        await session.refresh(session_launcher_secret_orm)
                    all_secrets.append(session_launcher_secret_orm.dump())
                    continue

                if secret_update.value is None:
                    # Remove the secret
                    session_launcher_secret_orm = existing_secrets_as_dict.get(slot_id)
                    if session_launcher_secret_orm is None:
                        continue
                    await session.delete(session_launcher_secret_orm)
                    del existing_secrets_as_dict[slot_id]
                    continue

                encrypted_value, encrypted_key = await self.user_repo.encrypt_user_secret(
                    requested_by=user,
                    secret_service_public_key=self.secret_service_public_key,
                    secret_value=secret_update.value,
                )
                if session_launcher_secret_orm := existing_secrets_as_dict.get(slot_id):
                    session_launcher_secret_orm.secret.update(
                        encrypted_value=encrypted_value, encrypted_key=encrypted_key
                    )
                else:
                    name = secret_slot.name
                    suffix = "".join([random.choice(string.ascii_lowercase + string.digits) for _ in range(8)])  # nosec B311
                    name_slug = base_models.Slug.from_name(name).value
                    default_filename = f"{name_slug[:200]}-{suffix}"
                    secret_orm = secrets_schemas.SecretORM(
                        name=name,
                        default_filename=default_filename,
                        user_id=user.id,
                        encrypted_value=encrypted_value,
                        encrypted_key=encrypted_key,
                        kind=SecretKind.general,
                    )
                    session_launcher_secret_orm = schemas.SessionSecretORM(
                        secret_slot_id=secret_update.secret_slot_id,
                        secret_id=secret_orm.id,
                        user_id=user.id,
                    )
                    session.add(secret_orm)
                    session.add(session_launcher_secret_orm)
                    await session.flush()
                    await session.refresh(session_launcher_secret_orm)
                all_secrets.append(session_launcher_secret_orm.dump())

            return all_secrets

    async def delete_session_secrets(
        self,
        user: base_models.APIUser,
        project_id: ULID,
    ) -> None:
        """Delete all session secrets associated with a project."""
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            result = await session.scalars(
                select(schemas.SessionSecretORM)
                .where(schemas.SessionSecretORM.user_id == user.id)
                .where(schemas.SessionSecretORM.secret_slot_id == schemas.SessionSecretSlotORM.id)
                .where(schemas.SessionSecretSlotORM.project_id == project_id)
            )
            for secret in result:
                await session.delete(secret)


class ProjectMigrationRepository:
    """Repository for project migrations."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        authz: Authz,
        project_repo: ProjectRepository,
        session_repo: SessionRepository,
    ) -> None:
        self.session_maker = session_maker
        self.authz = authz
        self.project_repo = project_repo
        self.session_repo = session_repo

    async def get_project_migrations(
        self,
        user: base_models.APIUser,
    ) -> AsyncGenerator[models.ProjectMigrationInfo, None]:
        """Get all project migrations from the database."""
        project_ids = await self.authz.resources_with_permission(user, user.id, ResourceType.project, Scope.READ)

        async with self.session_maker() as session:
            stmt = select(schemas.ProjectMigrationsORM).where(schemas.ProjectMigrationsORM.project_id.in_(project_ids))
            result = await session.stream_scalars(stmt)
            async for migration in result:
                yield migration.dump()

    @with_db_transaction
    @Authz.authz_change(AuthzOperation.create, ResourceType.project)
    async def migrate_v1_project(
        self,
        user: base_models.APIUser,
        project: models.UnsavedProject,
        project_v1_id: int,
        session_launcher: project_apispec.MigrationSessionLauncherPost | None = None,
        session: AsyncSession | None = None,
    ) -> models.Project:
        """Migrate a v1 project by creating a new project and tracking the migration."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required")

        result = await session.scalars(
            select(schemas.ProjectMigrationsORM).where(schemas.ProjectMigrationsORM.project_v1_id == project_v1_id)
        )
        project_migration = result.one_or_none()
        if project_migration is not None:
            raise errors.ValidationError(message=f"Project V1 with id '{project_v1_id}' already exists.")
        created_project = await self.project_repo.insert_project(user, project)
        if not created_project:
            raise errors.ValidationError(
                message=f"Failed to create a project for migration from v1 (project_v1_id={project_v1_id})."
            )

        result_launcher = None
        if session_launcher is not None:
            unsaved_session_launcher = session_apispec.SessionLauncherPost(
                name=session_launcher.name,
                project_id=str(created_project.id),
                description=None,
                resource_class_id=session_launcher.resource_class_id,
                disk_storage=session_launcher.disk_storage,
                environment=session_apispec.EnvironmentPostInLauncherHelper(
                    environment_kind=session_apispec.EnvironmentKind.CUSTOM,
                    name=session_launcher.name,
                    description=None,
                    container_image=session_launcher.container_image,
                    default_url=session_launcher.default_url,
                    uid=constants.MIGRATION_UID,
                    gid=constants.MIGRATION_GID,
                    working_directory=constants.MIGRATION_WORKING_DIRECTORY,
                    mount_directory=constants.MIGRATION_MOUNT_DIRECTORY,
                    port=constants.MIGRATION_PORT,
                    command=constants.MIGRATION_COMMAND,
                    args=constants.MIGRATION_ARGS,
                    is_archived=False,
                    environment_image_source=session_apispec.EnvironmentImageSourceImage.image,
                    strip_path_prefix=False,
                ),
                env_variables=None,
            )

            new_launcher = validate_unsaved_session_launcher(
                unsaved_session_launcher, builds_config=self.session_repo.builds_config
            )
            result_launcher = await self.session_repo.insert_launcher(user=user, launcher=new_launcher)

        migration_orm = schemas.ProjectMigrationsORM(
            project_id=created_project.id,
            project_v1_id=project_v1_id,
            launcher_id=result_launcher.id if result_launcher else None,
        )

        if migration_orm.project_id is None:
            raise errors.ValidationError(message="Project ID cannot be None for the migration entry.")

        session.add(migration_orm)
        await session.flush()
        await session.refresh(migration_orm)

        return created_project

    async def get_migration_by_v1_id(self, user: base_models.APIUser, v1_id: int) -> models.Project:
        """Retrieve all migration records for a given project v1 ID."""
        async with self.session_maker() as session:
            stmt = select(schemas.ProjectMigrationsORM).where(schemas.ProjectMigrationsORM.project_v1_id == v1_id)
            result = await session.execute(stmt)
            project_ids = result.scalars().first()

            if not project_ids:
                raise errors.MissingResourceError(message=f"Migration for project v1 with id '{v1_id}' does not exist.")

            # NOTE: Show only those projects that user has access to
            allowed_projects = await self.authz.resources_with_permission(
                user, user.id, ResourceType.project, Scope.READ
            )
            project_id_list = [project_ids.project_id]
            stmt = select(schemas.ProjectORM)
            stmt = stmt.where(schemas.ProjectORM.id.in_(project_id_list))
            stmt = stmt.where(schemas.ProjectORM.id.in_(allowed_projects))
            result = await session.execute(stmt)
            project_orm = result.scalars().first()

            if project_orm is None:
                raise errors.MissingResourceError(
                    message="Project migrated does not exist or you don't have permissions to open it."
                )

            return project_orm.dump()

    async def get_migration_by_project_id(
        self, user: base_models.APIUser, project_id: ULID
    ) -> models.ProjectMigrationInfo | None:
        """Retrieve migration info for a given project v2 ID."""

        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        project_ids = await self.authz.resources_with_permission(user, user.id, ResourceType.project, Scope.WRITE)

        async with self.session_maker() as session:
            stmt_project = select(schemas.ProjectORM.id).where(schemas.ProjectORM.id == project_id)
            stmt_project = stmt_project.where(schemas.ProjectORM.id.in_(project_ids))
            res_project = await session.scalar(stmt_project)
            if not res_project:
                raise errors.MissingResourceError(
                    message=f"Project with ID {project_id} does not exist or you do not have access to it."
                )

            stmt = select(schemas.ProjectMigrationsORM).where(schemas.ProjectMigrationsORM.project_id == project_id)
            result = await session.execute(stmt)
            project_migration_orm = result.scalars().first()

            if project_migration_orm:
                return models.ProjectMigrationInfo(
                    project_id=project_id,
                    v1_id=project_migration_orm.project_v1_id,
                    launcher_id=project_migration_orm.launcher_id,
                )

            return None
