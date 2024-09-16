"""Adapters for project database classes."""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Concatenate, ParamSpec, TypeVar

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.authz.authz import Authz, AuthzOperation, ResourceType
from renku_data_services.authz.models import Member, MembershipChange, Scope
from renku_data_services.base_api.pagination import PaginationRequest
from renku_data_services.message_queue import events
from renku_data_services.message_queue.avro_models.io.renku.events import v2 as avro_schema_v2
from renku_data_services.message_queue.db import EventRepository
from renku_data_services.message_queue.interface import IMessageQueue
from renku_data_services.message_queue.redis_queue import dispatch_message
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.project import apispec as project_apispec
from renku_data_services.project import models
from renku_data_services.project import orm as schemas
from renku_data_services.storage import orm as storage_schemas
from renku_data_services.users.orm import UserORM
from renku_data_services.utils.core import with_db_transaction


class ProjectRepository:
    """Repository for project."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        message_queue: IMessageQueue,
        event_repo: EventRepository,
        group_repo: GroupRepository,
        authz: Authz,
    ) -> None:
        self.session_maker = session_maker
        self.message_queue: IMessageQueue = message_queue
        self.event_repo: EventRepository = event_repo
        self.group_repo: GroupRepository = group_repo
        self.authz = authz

    async def get_projects(
        self, user: base_models.APIUser, pagination: PaginationRequest, namespace: str | None = None
    ) -> tuple[list[models.Project], int]:
        """Get all projects from the database."""
        project_ids = await self.authz.resources_with_permission(user, user.id, ResourceType.project, Scope.READ)

        async with self.session_maker() as session:
            stmt = select(schemas.ProjectORM)
            stmt = stmt.where(schemas.ProjectORM.id.in_(project_ids))
            if namespace:
                stmt = _filter_by_namespace_slug(stmt, namespace)
            stmt = stmt.limit(pagination.per_page).offset(pagination.offset)
            stmt = stmt.order_by(schemas.ProjectORM.creation_date.desc())
            stmt_count = (
                select(func.count()).select_from(schemas.ProjectORM).where(schemas.ProjectORM.id.in_(project_ids))
            )
            if namespace:
                stmt_count = _filter_by_namespace_slug(stmt_count, namespace)
            results = await session.scalars(stmt), await session.scalar(stmt_count)
            projects_orm = results[0].all()
            total_elements = results[1] or 0
            return [p.dump() for p in projects_orm], total_elements

    async def get_all_projects(self, requested_by: base_models.APIUser) -> list[models.Project]:
        """Get all projects from the database when reprovisioning."""
        if not requested_by.is_admin:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session:
            # NOTE: without awaiting the connection below, there are failures about how a connection has not
            # been established in the DB but the query is getting executed.
            _ = await session.connection()
            stmt = select(schemas.ProjectORM)
            results = await session.execute(stmt)
            projects_orms = results.scalars().all()
            return [p.dump() for p in projects_orms]

    async def get_project(self, user: base_models.APIUser, project_id: ULID) -> models.Project:
        """Get one project from the database."""
        authorized = await self.authz.has_permission(user, ResourceType.project, project_id, Scope.READ)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        async with self.session_maker() as session:
            stmt = select(schemas.ProjectORM).where(schemas.ProjectORM.id == project_id)
            result = await session.execute(stmt)
            project_orm = result.scalars().first()

            if project_orm is None:
                raise errors.MissingResourceError(message=f"Project with id '{project_id}' does not exist.")

            return project_orm.dump()

    async def get_project_by_namespace_slug(
        self, user: base_models.APIUser, namespace: str, slug: str
    ) -> models.Project:
        """Get one project from the database."""
        async with self.session_maker() as session:
            stmt = select(schemas.ProjectORM)
            stmt = _filter_by_namespace_slug(stmt, namespace)
            stmt = stmt.where(schemas.ProjectSlug.slug == slug.lower())
            result = await session.execute(stmt)
            project_orm = result.scalars().first()

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

            return project_orm.dump()

    @with_db_transaction
    @Authz.authz_change(AuthzOperation.create, ResourceType.project)
    @dispatch_message(avro_schema_v2.ProjectCreated)
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
            select(schemas.NamespaceORM).where(schemas.NamespaceORM.slug == project.namespace.lower())
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

        repositories = [schemas.ProjectRepositoryORM(url) for url in (project.repositories or [])]
        slug = project.slug or base_models.Slug.from_name(project.name).value
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
        )
        project_slug = schemas.ProjectSlug(slug, project_id=project_orm.id, namespace_id=ns.id)

        session.add(project_slug)
        session.add(project_orm)
        await session.flush()
        await session.refresh(project_orm)

        return project_orm.dump()

    @with_db_transaction
    @Authz.authz_change(AuthzOperation.update, ResourceType.project)
    @dispatch_message(avro_schema_v2.ProjectUpdated)
    async def update_project(
        self,
        user: base_models.APIUser,
        project_id: ULID,
        payload: dict[str, Any],
        etag: str | None = None,
        *,
        session: AsyncSession | None = None,
    ) -> models.ProjectUpdate:
        """Update a project entry."""
        project_id_str: str = str(project_id)
        if not session:
            raise errors.ProgrammingError(message="A database session is required")
        result = await session.scalars(select(schemas.ProjectORM).where(schemas.ProjectORM.id == project_id))
        project = result.one_or_none()
        if project is None:
            raise errors.MissingResourceError(message=f"The project with id '{project_id}' cannot be found")
        old_project = project.dump()

        required_scope = Scope.WRITE
        new_visibility = payload.get("visibility")
        if isinstance(new_visibility, str):
            new_visibility = models.Visibility(new_visibility)
        if "visibility" in payload and new_visibility != old_project.visibility:
            # NOTE: changing the visibility requires the user to be owner which means they should have DELETE permission
            required_scope = Scope.DELETE
        if "namespace" in payload and payload["namespace"] != old_project.namespace:
            # NOTE: changing the namespace requires the user to be owner which means they should have DELETE permission
            required_scope = Scope.DELETE
        authorized = await self.authz.has_permission(user, ResourceType.project, project_id, required_scope)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        current_etag = project.dump().etag
        if etag is not None and current_etag != etag:
            raise errors.ConflictError(message=f"Current ETag is {current_etag}, not {etag}.")

        if "repositories" in payload:
            payload["repositories"] = [
                schemas.ProjectRepositoryORM(url=r, project_id=project_id_str, project=project)
                for r in payload["repositories"]
            ]
            # Trigger update for ``updated_at`` column
            await session.execute(update(schemas.ProjectORM).where(schemas.ProjectORM.id == project_id).values())

        if "keywords" in payload and not payload["keywords"]:
            payload["keywords"] = None

        for key, value in payload.items():
            # NOTE: ``slug``, ``id``, ``created_by``, and ``creation_date`` cannot be edited or cannot
            # be edited by setting a property on the ORM object instance.
            if key not in ["slug", "id", "created_by", "creation_date", "namespace"]:
                setattr(project, key, value)

        if "namespace" in payload:
            ns_slug = payload["namespace"]
            ns = await session.scalar(select(schemas.NamespaceORM).where(schemas.NamespaceORM.slug == ns_slug.lower()))
            if not ns:
                raise errors.MissingResourceError(message=f"The namespace with slug {ns_slug} does not exist")
            if not ns.group_id and not ns.user_id:
                raise errors.ProgrammingError(message="Found a namespace that has no group or user associated with it.")
            resource_type, resource_id = (
                (ResourceType.group, ns.group_id) if ns.group and ns.group_id else (ResourceType.user_namespace, ns.id)
            )
            has_permission = await self.authz.has_permission(user, resource_type, resource_id, Scope.WRITE)
            if not has_permission:
                raise errors.ForbiddenError(
                    message=f"The project cannot be created because you do not have sufficient permissions with the namespace {ns_slug}"  # noqa: E501
                )
            project.slug.namespace_id = ns.id

        await session.flush()
        await session.refresh(project)

        return models.ProjectUpdate(
            old=old_project,
            new=project.dump(),  # NOTE: Triggers validation before the transaction saves data
        )

    @with_db_transaction
    @Authz.authz_change(AuthzOperation.delete, ResourceType.project)
    @dispatch_message(avro_schema_v2.ProjectRemoved)
    async def delete_project(
        self, user: base_models.APIUser, project_id: ULID, *, session: AsyncSession | None = None
    ) -> models.Project | None:
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

        await session.execute(delete(schemas.ProjectORM).where(schemas.ProjectORM.id == project_id))

        await session.execute(
            delete(storage_schemas.CloudStorageORM).where(storage_schemas.CloudStorageORM.project_id == str(project_id))
        )

        return project.dump()


_P = ParamSpec("_P")
_T = TypeVar("_T")


def _filter_by_namespace_slug(statement: Select[tuple[_T]], namespace: str) -> Select[tuple[_T]]:
    """Filters a select query on projects to a given namespace."""
    return (
        statement.where(schemas.NamespaceORM.slug == namespace.lower())
        .where(schemas.ProjectSlug.namespace_id == schemas.NamespaceORM.id)
        .where(schemas.ProjectORM.id == schemas.ProjectSlug.project_id)
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
        event_repo: EventRepository,
        authz: Authz,
        message_queue: IMessageQueue,
    ) -> None:
        self.session_maker = session_maker
        self.event_repo = event_repo
        self.authz = authz
        self.message_queue = message_queue

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
    @dispatch_message(events.ProjectMembershipChanged)
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
    @dispatch_message(events.ProjectMembershipChanged)
    async def delete_members(
        self, user: base_models.APIUser, project_id: ULID, user_ids: list[str], *, session: AsyncSession | None = None
    ) -> list[MembershipChange]:
        """Delete members from a project."""
        if len(user_ids) == 0:
            raise errors.ValidationError(message="Please request at least 1 member to be removed from the project")

        members = await self.authz.remove_project_members(user, ResourceType.project, project_id, user_ids)
        return members
