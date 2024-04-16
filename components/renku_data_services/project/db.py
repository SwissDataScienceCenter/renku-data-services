"""Adapters for project database classes."""

from __future__ import annotations

from asyncio import gather
from collections.abc import Callable
from typing import Any, NamedTuple, cast

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.authz import models as authz_models
from renku_data_services.authz.authz import IProjectAuthorizer
from renku_data_services.authz.models import MemberQualifier, Scope
from renku_data_services.base_api.pagination import PaginationRequest
from renku_data_services.message_queue.avro_models.io.renku.events.v1.project_created import ProjectCreated
from renku_data_services.message_queue.avro_models.io.renku.events.v1.project_removed import ProjectRemoved
from renku_data_services.message_queue.avro_models.io.renku.events.v1.project_updated import ProjectUpdated
from renku_data_services.message_queue.avro_models.io.renku.events.v1.visibility import Visibility as MsgVisibility
from renku_data_services.message_queue.db import EventRepository
from renku_data_services.message_queue.interface import IMessageQueue
from renku_data_services.message_queue.redis_queue import dispatch_message
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.project import apispec, models
from renku_data_services.project import orm as schemas
from renku_data_services.project.apispec import Role, Visibility
from renku_data_services.utils.core import with_db_transaction


def convert_to_authz_role(role: Role) -> authz_models.Role:
    """Covert from project member Role to authz Role."""
    return authz_models.Role.OWNER if role == Role.owner else authz_models.Role.MEMBER


def convert_from_authz_role(role: authz_models.Role) -> Role:
    """Covert from authz Role to project member Role."""
    return Role.owner if role == authz_models.Role.OWNER else Role.member


class PaginationResponse(NamedTuple):
    """Paginated response."""

    page: int
    per_page: int
    total: int
    total_pages: int


def create_project_created_message(result: models.Project, *_, **__) -> ProjectCreated:
    """Transform project to message queue message."""
    match result.visibility:
        case Visibility.private | Visibility.private.value:
            vis = MsgVisibility.PRIVATE
        case Visibility.public | Visibility.public.value:
            vis = MsgVisibility.PUBLIC
        case _:
            raise NotImplementedError(f"unknown visibility:{result.visibility}")

    assert result.id is not None
    assert result.creation_date is not None

    return ProjectCreated(
        id=result.id,
        name=result.name,
        slug=result.slug,
        repositories=result.repositories,
        visibility=vis,
        description=result.description,
        createdBy=result.created_by,
        creationDate=result.creation_date,
        keywords=[],
    )


def create_project_update_message(result: models.Project, *_, **__) -> ProjectUpdated:
    """Transform project to message queue message."""
    match result.visibility:
        case Visibility.private | Visibility.private.value:
            vis = MsgVisibility.PRIVATE
        case Visibility.public | Visibility.public.value:
            vis = MsgVisibility.PUBLIC
        case _:
            raise NotImplementedError(f"unknown visibility:{result.visibility}")

    assert result.id is not None
    return ProjectUpdated(
        id=result.id,
        name=result.name,
        slug=result.slug,
        repositories=result.repositories,
        visibility=vis,
        description=result.description,
        keywords=[],
    )


def create_project_removed_message(result, *_, **__) -> ProjectRemoved | None:
    """Transform project removal to message queue message."""
    if result is None:
        return None
    return ProjectRemoved(id=result)


class ProjectRepository:
    """Repository for project."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        project_authz: IProjectAuthorizer,
        message_queue: IMessageQueue,
        event_repo: EventRepository,
        group_repo: GroupRepository,
    ):
        self.session_maker = session_maker  # type: ignore[call-overload]
        self.project_authz: IProjectAuthorizer = project_authz
        self.message_queue: IMessageQueue = message_queue
        self.event_repo: EventRepository = event_repo
        self.group_repo: GroupRepository = group_repo

    async def get_projects(
        self,
        user: base_models.APIUser,
        pagination: PaginationRequest,
    ) -> tuple[list[models.Project], int]:
        """Get all projects from the database."""
        user_id = user.id if user.is_authenticated else MemberQualifier.ALL
        # NOTE: without the line below mypy thinks user_id can be None
        user_id = user_id if user_id is not None else MemberQualifier.ALL
        project_ids = await self.project_authz.get_user_projects(requested_by=user, user_id=user_id, scope=Scope.READ)

        async with self.session_maker() as session:
            stmt = select(schemas.ProjectORM)
            stmt = stmt.where(schemas.ProjectORM.id.in_(project_ids))
            stmt = stmt.limit(pagination.per_page).offset(pagination.offset)
            stmt = stmt.order_by(schemas.ProjectORM.creation_date.desc())
            stmt_count = (
                select(func.count()).select_from(schemas.ProjectORM).where(schemas.ProjectORM.id.in_(project_ids))
            )

            results = await gather(session.execute(stmt), session.execute(stmt_count))
            projects_orm = results[0].scalars().all()
            total_elements = cast(int, results[1].scalar() or 0)

            return [p.dump() for p in projects_orm], total_elements

    async def get_project(self, user: base_models.APIUser, project_id: str) -> models.Project:
        """Get one project from the database."""
        authorized = await self.project_authz.has_permission(user=user, project_id=project_id, scope=Scope.READ)
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
            stmt = (
                select(schemas.ProjectORM)
                .where(schemas.NamespaceORM.slug == namespace.lower())
                .where(schemas.ProjectSlug.namespace_id == schemas.NamespaceORM.id)
                .where(schemas.ProjectSlug.slug == slug.lower())
                .where(schemas.ProjectORM.id == schemas.ProjectSlug.project_id)
            )
            result = await session.execute(stmt)
            project_orm = result.scalars().first()

            not_found_msg = (
                f"Project with identifier '{namespace}/{slug}' does not exist or you do not have access to it."
            )

            if project_orm is None:
                raise errors.MissingResourceError(message=not_found_msg)

            authorized = await self.project_authz.has_permission(user=user, project_id=project_orm.id, scope=Scope.READ)
            if not authorized:
                raise errors.MissingResourceError(message=not_found_msg)

            return project_orm.dump()

    @with_db_transaction
    @dispatch_message(create_project_created_message)
    async def insert_project(
        self, session: AsyncSession, user: base_models.APIUser, new_project=apispec.ProjectPost
    ) -> models.Project:
        """Insert a new project entry."""
        ns = await self.group_repo.get_namespace(user, new_project.namespace)
        if not ns:
            raise errors.MissingResourceError(
                message=f"The project cannot be created because the namespace {new_project.namespace} does not exist"
            )

        if user.id is None:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")

        repositories = [schemas.ProjectRepositoryORM(url) for url in (new_project.repositories or [])]
        project_slug = new_project.slug or base_models.Slug.from_name(new_project.name).value
        project = schemas.ProjectORM(
            name=new_project.name,
            visibility=(
                models.Visibility(new_project.visibility)
                if isinstance(new_project.visibility, str)
                else new_project.visibility
            ),
            created_by_id=user.id,
            description=new_project.description,
            repositories=repositories,
        )
        slug = schemas.ProjectSlug(project_slug, project_id=project.id, namespace_id=ns.id)

        session.add(slug)
        session.add(project)
        await session.flush()
        await session.refresh(project)

        project_model = project.dump()
        public_project = project_model.visibility == Visibility.public
        if project_model.id is None:
            raise errors.BaseError(detail="The created project does not have an ID but it should.")
        await self.project_authz.create_project(
            requested_by=user, project_id=project_model.id, public_project=public_project
        )

        return project.dump()

    @with_db_transaction
    @dispatch_message(create_project_update_message)
    async def update_project(
        self, session: AsyncSession, user: base_models.APIUser, project_id: str, etag: str | None = None, **payload
    ) -> models.Project:
        """Update a project entry."""
        authorized = await self.project_authz.has_permission(user=user, project_id=project_id, scope=Scope.WRITE)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        result = await session.scalars(select(schemas.ProjectORM).where(schemas.ProjectORM.id == project_id))
        project = result.one_or_none()

        if project is None:
            raise errors.MissingResourceError(message=f"The project with id '{project_id}' cannot be found")

        current_etag = project.dump().etag
        if etag is not None and current_etag != etag:
            raise errors.ConflictError(message=f"Current ETag is {current_etag}, not {etag}.")

        visibility_before = project.visibility

        if "repositories" in payload:
            payload["repositories"] = [
                schemas.ProjectRepositoryORM(url=r, project_id=project_id, project=project)
                for r in payload["repositories"]
            ]
            # Trigger update for ``updated_at`` column
            await session.execute(update(schemas.ProjectORM).where(schemas.ProjectORM.id == project_id).values())

        for key, value in payload.items():
            # NOTE: ``slug``, ``id``, ``created_by``, and ``creation_date`` cannot be edited or cannot
            # be edited by setting a property on the ORM object instance.
            if key not in ["slug", "id", "created_by", "creation_date", "namespace"]:
                setattr(project, key, value)

        if "namespace" in payload:
            ns_slug = payload["namespace"]
            ns = await self.group_repo.get_namespace(user, ns_slug)
            if not ns:
                raise errors.MissingResourceError(message=f"The namespace with slug {ns_slug} does not exist")
            project.slug.namespace_id = ns.id
            # await session.refresh(project)

        if visibility_before != project.visibility:
            public_project = project.visibility == Visibility.public
            await self.project_authz.update_project_visibility(
                requested_by=user, project_id=project_id, public_project=public_project
            )

        await session.flush()
        await session.refresh(project)

        return project.dump()  # NOTE: Triggers validation before the transaction saves data

    @with_db_transaction
    @dispatch_message(create_project_removed_message)
    async def delete_project(self, session: AsyncSession, user: base_models.APIUser, project_id: str) -> str | None:
        """Delete a cloud project entry."""
        authorized = await self.project_authz.has_permission(user=user, project_id=project_id, scope=Scope.DELETE)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        result = await session.execute(select(schemas.ProjectORM).where(schemas.ProjectORM.id == project_id))
        projects = result.one_or_none()

        if projects is None:
            return None

        await session.execute(delete(schemas.ProjectORM).where(schemas.ProjectORM.id == projects[0].id))

        await self.project_authz.delete_project(requested_by=user, project_id=project_id)
        return project_id


class ProjectMemberRepository:
    """Repository for project members."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        project_authz: IProjectAuthorizer,
    ):
        self.session_maker = session_maker  # type: ignore[call-overload]
        self.project_authz: IProjectAuthorizer = project_authz

    async def get_members(self, user: base_models.APIUser, project_id: str) -> list[models.MemberWithRole]:
        """Get all members of a project."""
        authorized = await self.project_authz.has_permission(user=user, project_id=project_id, scope=Scope.READ)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        members = await self.project_authz.get_project_users(requested_by=user, project_id=project_id, scope=Scope.READ)

        return [models.MemberWithRole(member=m.user_id, role=convert_from_authz_role(m.role)) for m in members]

    async def update_members(self, user: base_models.APIUser, project_id: str, members: list[dict[str, Any]]) -> None:
        """Update project's members."""
        authorized = await self.project_authz.has_permission(user=user, project_id=project_id, scope=Scope.WRITE)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        async with self.session_maker() as session, session.begin():
            result = await session.execute(select(schemas.ProjectORM).where(schemas.ProjectORM.id == project_id))
            project = result.one_or_none()
            if project is None:
                raise errors.MissingResourceError(message=f"The project with id '{project_id}' cannot be found")

            for member in members:
                await self.project_authz.update_or_add_user(
                    requested_by=user,
                    project_id=project_id,
                    user_id=member["id"],
                    role=convert_to_authz_role(Role(member["role"])),
                )

    async def delete_member(self, user: base_models.APIUser, project_id: str, member_id: str) -> None:
        """Delete a single member from a project."""
        authorized = await self.project_authz.has_permission(user=user, project_id=project_id, scope=Scope.WRITE)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        async with self.session_maker() as session, session.begin():
            result = await session.execute(select(schemas.ProjectORM).where(schemas.ProjectORM.id == project_id))
            project = result.one_or_none()
            if project is None:
                raise errors.MissingResourceError(message=f"The project with id '{project_id}' cannot be found")

            await self.project_authz.delete_user(requested_by=user, project_id=project_id, user_id=member_id)
