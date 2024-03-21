"""Adapters for project database classes."""

from __future__ import annotations

from asyncio import gather
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, NamedTuple, Tuple, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.authz import models as authz_models
from renku_data_services.authz.authz import IProjectAuthorizer
from renku_data_services.authz.models import MemberQualifier, Scope
from renku_data_services.base_api.pagination import PaginationRequest
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.project.apispec import ProjectPost, Role, Visibility
from renku_data_services.message_queue.avro_models.io.renku.events.v1.project_created import ProjectCreated
from renku_data_services.message_queue.avro_models.io.renku.events.v1.project_removed import ProjectRemoved
from renku_data_services.message_queue.avro_models.io.renku.events.v1.project_updated import ProjectUpdated
from renku_data_services.message_queue.avro_models.io.renku.events.v1.visibility import Visibility as MsgVisibility
from renku_data_services.message_queue.db import EventRepository
from renku_data_services.message_queue.interface import IMessageQueue
from renku_data_services.message_queue.redis_queue import dispatch_message
from renku_data_services.project import models
from renku_data_services.project import orm as schemas
from renku_data_services.utils.core import with_db_transaction


def convert_to_authz_role(role: Role) -> authz_models.Role:
    """Covert from project member Role to authz Role."""
    return authz_models.Role.OWNER if role == Role.owner else authz_models.Role.MEMBER


def convert_from_authz_role(role: authz_models.Role) -> Role:
    """Covert from authz Role to project member Role."""
    return Role.owner if authz_models.Role.OWNER == role else Role.member


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
        createdBy=result.created_by.id,
        creationDate=result.creation_date,
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
    ) -> Tuple[list[models.Project], int]:
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
            n_total_elements = cast(int, results[1].scalar() or 0)

            return [p.dump() for p in projects_orm], n_total_elements

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

    async def insert_project(self, user: base_models.APIUser, project: ProjectPost) -> models.Project:
        """Insert a new project entry."""
        ns, _ = await self.group_repo.get_ns_group_orm(user, project.namespace)
        if not ns:
            raise errors.MissingResourceError(
                message=f"The project cannot be created because the namespace {project.namespace} does not exist"
            )
        user_id = cast(str, user.id)
        repos = [schemas.ProjectRepositoryORM(url) for url in (project.repositories or [])]
        slug = project.slug or models.get_slug(project.name)
        if isinstance(project.visibility, str):
            project.visibility = models.Visibility(project.visibility)
        project_orm = schemas.ProjectORM(
            name=project.name,
            visibility=project.visibility,
            created_by_id=user_id,
            description=project.description,
            ltst_prj_slug=schemas.ProjectSlug(slug, ltst_ns_slug=ns.ltst_ns_slug or ns),
            repositories=repos,
            creation_date=datetime.now(timezone.utc).replace(microsecond=0),
        )

        match project_orm.visibility:
            case Visibility.private | Visibility.private.value:
                vis = MsgVisibility.PRIVATE
            case Visibility.public | Visibility.public.value:
                vis = MsgVisibility.PUBLIC
            case _:
                raise NotImplementedError(f"unknown visibility:{project_orm.visibility}")

        async with self.message_queue.project_created_message(
            name=project_orm.name,
            slug=project_orm.ltst_prj_slug.slug,
            visibility=vis,
            id=project_orm.id,
            repositories=[r.url for r in project_orm.repositories],
            description=project_orm.description,
            creation_date=project_orm.creation_date,
            created_by=project_orm.created_by_id,
        ) as message:
            async with self.session_maker() as session:
                async with session.begin():
                    session.add(project_orm)
                    await session.flush()
                    if project_orm.id is None:
                        raise errors.BaseError(detail="The created project does not have an ID but it should.")
                    await self.project_authz.create_project(
                        requested_by=user,
                        project_id=project_orm.id,
                        public_project=project_orm.visibility.value == models.Visibility.public.value,
                    )
                    await message.persist(self.event_repo)

    @with_db_transaction
    @dispatch_message(create_project_created_message)
    async def insert_project(
        self, session: AsyncSession, user: base_models.APIUser, project: models.Project
    ) -> models.Project:
        """Insert a new project entry."""
        ns, _ = await self.group_repo.get_ns_group_orm(user, project.namespace)
        if not ns:
            raise errors.MissingResourceError(
                message=f"The project cannot be created because the namespace {project.namespace} does not exist"
            )
        user_id = cast(str, user.id)
        repos = [schemas.ProjectRepositoryORM(url) for url in (project.repositories or [])]
        slug = project.slug or models.get_slug(project.name)
        if isinstance(project.visibility, str):
            project.visibility = models.Visibility(project.visibility)
        project_orm = schemas.ProjectORM(
            name=project.name,
            visibility=project.visibility,
            created_by_id=user_id,
            description=project.description,
            ltst_prj_slug=schemas.ProjectSlug(slug, ltst_ns_slug=ns.ltst_ns_slug or ns),
            repositories=repos,
            creation_date=datetime.now(timezone.utc).replace(microsecond=0),
        )
        session.add(project_orm)
        await session.flush()

        project_dump = project_orm.dump()
        public_project = project_dump.visibility == Visibility.public
        if project_dump.id is None:
            raise errors.BaseError(detail="The created project does not have an ID but it should.")
        await self.project_authz.create_project(requested_by=user, project_id=project_dump.id, public_project=public_project)

        return project_dump

    @with_db_transaction
    @dispatch_message(create_project_update_message)
    async def update_project(
        self, session: AsyncSession, user: base_models.APIUser, project_id: str, **payload
    ) -> models.Project:
        """Update a project entry."""
        authorized = await self.project_authz.has_permission(user=user, project_id=project_id, scope=Scope.WRITE)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        result = await session.execute(select(schemas.ProjectORM).where(schemas.ProjectORM.id == project_id))
        project = result.scalar_one_or_none()

        if project is None:
            raise errors.MissingResourceError(message=f"The project with id '{project_id}' cannot be found")

        visibility_before = project.visibility
        session.add(project)  # reattach to session
        if "repositories" in payload:
            payload["repositories"] = [
                schemas.ProjectRepositoryORM(url=r, project_id=project_id, project=project)
                for r in payload["repositories"]
            ]

        for key, value in payload.items():
            # NOTE: ``slug``, ``id``, ``created_by``, and ``creation_date`` cannot be edited
            if key not in ["slug", "id", "created_by", "creation_date"]:
                setattr(project, key, value)

        if visibility_before != project.visibility:
            public_project = project.visibility == Visibility.public
            await self.project_authz.update_project_visibility(
                requested_by=user, project_id=project_id, public_project=public_project
            )

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

        await session.delete(projects[0])

        await self.project_authz.delete_project(requested_by=user, project_id=project_id)
        return project_id


class ProjectMemberRepository:
    """Repository for project members."""

    def __init__(self, session_maker: Callable[..., AsyncSession], project_authz: IProjectAuthorizer):
        self.session_maker = session_maker  # type: ignore[call-overload]
        self.project_authz: IProjectAuthorizer = project_authz

    async def get_members(self, user: base_models.APIUser, project_id: str) -> List[models.MemberWithRole]:
        """Get all members of a project."""
        authorized = await self.project_authz.has_permission(user=user, project_id=project_id, scope=Scope.READ)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        members = await self.project_authz.get_project_users(requested_by=user, project_id=project_id, scope=Scope.READ)

        return [models.MemberWithRole(member=m.user_id, role=convert_from_authz_role(m.role)) for m in members]

    async def update_members(self, user: base_models.APIUser, project_id: str, members: List[Dict[str, Any]]) -> None:
        """Update project's members."""
        authorized = await self.project_authz.has_permission(user=user, project_id=project_id, scope=Scope.WRITE)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        async with self.session_maker() as session:
            async with session.begin():
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

        async with self.session_maker() as session:
            async with session.begin():
                result = await session.execute(select(schemas.ProjectORM).where(schemas.ProjectORM.id == project_id))
                project = result.one_or_none()
                if project is None:
                    raise errors.MissingResourceError(message=f"The project with id '{project_id}' cannot be found")

                await self.project_authz.delete_user(requested_by=user, project_id=project_id, user_id=member_id)
