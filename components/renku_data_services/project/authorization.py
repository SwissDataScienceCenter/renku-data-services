"""Projects authorization adapter."""
from dataclasses import dataclass, field
from typing import Any, Callable, List, Protocol, Tuple

from sqlalchemy import create_engine, delete, select, Engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, AsyncEngine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import or_


from renku_data_services.project.models import AccessLevel, PermissionQualifier
from renku_data_services.base_models.core import APIUser
from renku_data_services.project.orm import ProjectUserAuthz
from renku_data_services.errors import errors


class IProjectAuthorizer(Protocol):
    """An interface for a project authorization adapter."""

    async def has_permission(self, user: APIUser, project_id: str, access_level: AccessLevel) -> bool:
        """Whether the permissions granted to the user for the project are match access level."""
        ...

    async def project_accessible_by(
        self, requested_by: APIUser, project_id: str, access_level: AccessLevel
    ) -> Tuple[PermissionQualifier, List[str]]:
        """Which users have the access level on a project."""
        ...

    async def user_can_access(
        self, requested_by: APIUser, user_id: str | PermissionQualifier, access_level: AccessLevel
    ) -> List[str]:
        """The projects to which the user has a specific access level."""
        ...

    async def grant_permission(
        self, requested_by: APIUser, user_id: str | PermissionQualifier, project_id: str, access_level: AccessLevel
    ):
        """Grant the specific permission level to the user for the specific project."""
        ...

    async def create_project(self, requested_by: APIUser, project_id: str, public_project: bool = False):
        """Insert the project in the authorization records."""
        ...

    async def delete_project(self, requested_by: APIUser, project_id: str):
        """Remove all instances of the project the authorization records."""
        ...


@dataclass
class SQLProjectAuthorizer:
    """Adapter to store authorization data for projects in SQL."""

    sync_sqlalchemy_url: str = field(repr=False)
    async_sqlalchemy_url: str = field(repr=False)
    debug: bool = False
    engine: AsyncEngine = field(init=False)
    sync_engine: Engine = field(init=False)
    session_maker: Callable[..., AsyncSession] = field(init=False)

    def __post_init__(self, *args, **kwargs):
        self.engine = create_async_engine(self.async_sqlalchemy_url, echo=self.debug)
        self.sync_engine = create_engine(self.sync_sqlalchemy_url, echo=self.debug)
        self.session_maker = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )  # type: ignore[call-overload]

    async def has_permission(self, user: APIUser, project_id: str, access_level: AccessLevel) -> bool:
        """Whether the permissions granted to the user for the project match the access level."""
        stmt = select(ProjectUserAuthz).where(ProjectUserAuthz.project_id == project_id)
        if not user.is_admin:
            # NOTE: the specific user should have the required access level OR
            # the user field should be NULL in the db (which means it applies to users)
            stmt = stmt.where(
                ProjectUserAuthz.access_level >= access_level.value,
            ).where(or_(ProjectUserAuthz.user_id == user.id, ProjectUserAuthz.user_id.is_(None)))
        permission = None
        async with self.session_maker() as session:
            res = await session.execute(stmt)
            permission = res.scalars().first()
        return permission is not None

    async def project_accessible_by(
        self, requested_by: APIUser, project_id: str, access_level: AccessLevel
    ) -> Tuple[PermissionQualifier, List[str]]:
        """Which users have been granted permissions to the project at the access level."""
        async with self.session_maker() as session:
            if not requested_by.is_authenticated:
                raise errors.Unauthorized(message="Unauthenticated users cannot query permissions of other users.")
            if not requested_by.is_admin:
                requested_by_owner = await self.has_permission(requested_by, project_id, AccessLevel.OWNER)
                if not requested_by_owner:
                    raise errors.Unauthorized(message="Only the owner of the project can see who has access to it.")
            stmt = (
                select(ProjectUserAuthz.user_id)
                .distinct()
                .where(ProjectUserAuthz.project_id == project_id)
                .where(ProjectUserAuthz.access_level >= access_level.value)
            )
            res = await session.execute(stmt)
            users = res.scalars().all()
            users_list = [i for i in users]
            if len(users_list) == 0:
                return PermissionQualifier.NONE, []
            elif None in users_list:
                return PermissionQualifier.ALL, []
            else:
                return PermissionQualifier.SOME, users_list  # type: ignore[return-value]

    async def user_can_access(
        self, requested_by: APIUser, user_id: str | PermissionQualifier, access_level: AccessLevel
    ) -> List[str]:
        """Which project IDs can a specific user access at the designated access level."""
        if not requested_by.is_authenticated and user_id != PermissionQualifier.ALL:
            raise errors.Unauthorized(message="Unauthenticated users cannot query permissions of specific users.")
        if requested_by.is_authenticated and not requested_by.is_admin and user_id != requested_by.id:
            raise errors.Unauthorized(message="Users can access only their own permission information")
        stmt = select(ProjectUserAuthz.project_id).distinct().where(ProjectUserAuthz.access_level >= access_level.value)
        query_filters: List[Any] = []
        if isinstance(user_id, PermissionQualifier):
            if user_id != PermissionQualifier.ALL:
                raise errors.ValidationError(
                    message="When checking user permissions the only "
                    f"acceptable qualifier is ALL, you provided {user_id}"
                )
            if user_id == PermissionQualifier.ALL:
                query_filters.append(ProjectUserAuthz.user_id.is_(None))
        if not requested_by.is_admin and not isinstance(user_id, PermissionQualifier):
            query_filters.append(or_(ProjectUserAuthz.user_id == user_id, ProjectUserAuthz.user_id.is_(None)))
        async with self.session_maker() as session:
            res = await session.execute(stmt.where(*query_filters))
            projects = res.scalars().all()
        return [i for i in projects]

    async def grant_permission(
        self, requested_by: APIUser, user_id: str | PermissionQualifier, project_id: str, access_level: AccessLevel
    ):
        """Grant the specific permission level to the user for the specific project."""
        if not requested_by.is_authenticated:
            raise errors.Unauthorized(message="Unauthenticated users cannot edit project permissions.")
        if isinstance(user_id, PermissionQualifier):
            if user_id != PermissionQualifier.ALL:
                raise errors.ValidationError(
                    message=f"Valid qualifier for granting permissions in only ALL, received {user_id}."
                )
        if not requested_by.is_admin:
            can_grant_permission = await self.has_permission(requested_by, project_id, AccessLevel.OWNER)
            if not can_grant_permission:
                raise errors.Unauthorized(
                    message=f"The user with ID {requested_by.id} cannot grant access to project with ID {project_id}",
                    detail=f"Only users with {AccessLevel.OWNER} access level can do this.",
                )
        async with self.session_maker() as session:
            async with session.begin():
                session.add(
                    ProjectUserAuthz(
                        project_id=project_id,
                        access_level=access_level.value,
                        user_id=None  # type: ignore[arg-type]
                        if isinstance(user_id, PermissionQualifier) and user_id == PermissionQualifier.ALL
                        else user_id,
                    )
                )

    async def create_project(self, requested_by: APIUser, project_id: str, public_project: bool = False):
        """Insert the project in the authorization table."""
        if not requested_by.is_authenticated:
            raise errors.Unauthorized(message="Unauthenticated users cannot create projects.")
        async with self.session_maker() as session:
            async with session.begin():
                res = await session.execute(
                    select(ProjectUserAuthz.project_id).where(ProjectUserAuthz.project_id == project_id)
                )
                project_exists = res.scalars().first()
                if project_exists:
                    raise errors.ValidationError(
                        message="Cannot create a project if it already exists in the permissions database"
                    )
                if public_project:
                    session.add(
                        ProjectUserAuthz(
                            project_id=project_id, access_level=AccessLevel.PUBLIC_ACCESS.value, user_id=None
                        )
                    )
                session.add(
                    ProjectUserAuthz(
                        project_id=project_id, access_level=AccessLevel.OWNER.value, user_id=requested_by.id
                    )
                )

    async def delete_project(self, requested_by: APIUser, project_id: str):
        """Delete all instances of the project in the authorization table."""
        if not requested_by.is_authenticated:
            raise errors.Unauthorized(message="Unauthenticated users cannot delete projects.")
        async with self.session_maker() as session:
            async with session.begin():
                del_stmt = delete(ProjectUserAuthz).where(ProjectUserAuthz.project_id == project_id)
                if not requested_by.is_admin:
                    user_is_owner = self.has_permission(requested_by, project_id, AccessLevel.OWNER)
                    if not user_is_owner:
                        raise errors.Unauthorized(
                            message="Only the owner or admin can remove a project from the permissions."
                        )
                await session.execute(del_stmt)
