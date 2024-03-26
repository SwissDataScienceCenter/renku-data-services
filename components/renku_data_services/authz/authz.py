"""Projects authorization adapter."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, cast

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services.authz.models import MemberQualifier, ProjectMember, Role, Scope
from renku_data_services.authz.orm import ProjectUserAuthz
from renku_data_services.base_models.core import APIUser
from renku_data_services.errors import errors
from renku_data_services.message_queue.avro_models.io.renku.events.v1.project_authorization_added import (
    ProjectAuthorizationAdded,
)
from renku_data_services.message_queue.avro_models.io.renku.events.v1.project_authorization_removed import (
    ProjectAuthorizationRemoved,
)
from renku_data_services.message_queue.avro_models.io.renku.events.v1.project_authorization_updated import (
    ProjectAuthorizationUpdated,
)
from renku_data_services.message_queue.avro_models.io.renku.events.v1.project_member_role import ProjectMemberRole
from renku_data_services.message_queue.db import EventRepository
from renku_data_services.message_queue.interface import IMessageQueue
from renku_data_services.message_queue.redis_queue import dispatch_message
from renku_data_services.utils.core import with_db_transaction


class IProjectAuthorizer(Protocol):
    """An interface for a project authorization adapter."""

    async def has_permission(self, user: APIUser, project_id: str, scope: Scope) -> bool:
        """Whether the user has specific permission on a specific project."""
        ...

    async def has_role(self, user: APIUser, project_id: str, role: Role) -> bool:
        """Whether the user is a member of the project with the specific role."""
        ...

    async def get_project_qualifier_and_users(
        self, requested_by: APIUser, project_id: str, scope: Scope
    ) -> tuple[MemberQualifier, list[str]]:
        """Which users have the specific permission on a project considering member qualifier."""
        ...

    async def get_project_users(self, requested_by: APIUser, project_id: str, scope: Scope) -> list[ProjectMember]:
        """Get users that have explicit access to a project."""
        ...

    async def get_user_projects(self, requested_by: APIUser, user_id: str | MemberQualifier, scope: Scope) -> list[str]:
        """The projects to which the user has specific permission."""
        ...

    async def add_user(self, requested_by: APIUser, user_id: str | MemberQualifier, project_id: str, role: Role):
        """Grant the specific permission level to the user for the specific project."""
        ...

    async def update_or_add_user(
        self, requested_by: APIUser, user_id: str | MemberQualifier, project_id: str, role: Role
    ):
        """Update user's role or add user if it doesn't exist."""
        ...

    async def delete_user(self, requested_by: APIUser, user_id: str | MemberQualifier, project_id: str):
        """Delete a member from a project."""
        ...

    async def create_project(self, requested_by: APIUser, project_id: str, public_project: bool = False):
        """Insert the project in the authorization records."""
        ...

    async def update_project_visibility(self, requested_by: APIUser, project_id: str, public_project: bool):
        """Change project's qualifier accordingly."""
        ...

    async def delete_project(self, requested_by: APIUser, project_id: str):
        """Remove all instances of the project the authorization records."""
        ...


def create_project_auth_added_message(result: ProjectUserAuthz, *_, **__) -> ProjectAuthorizationAdded | None:
    """Transform project authz to message queue message."""
    if result.user_id is None:
        return None
    return ProjectAuthorizationAdded(
        projectId=result.project_id,
        userId=result.user_id,
        role=ProjectMemberRole.OWNER if result.role == Role.OWNER.value else ProjectMemberRole.MEMBER,
    )


def create_project_auth_updated_message(result: ProjectUserAuthz, **_) -> ProjectAuthorizationUpdated | None:
    """Transform project authz to message queue message."""
    if result.user_id is None:
        return None
    return ProjectAuthorizationUpdated(
        projectId=result.project_id,
        userId=result.user_id,
        role=ProjectMemberRole.OWNER if result.role == Role.OWNER.value else ProjectMemberRole.MEMBER,
    )


def create_project_auth_removed_message(
    result: ProjectUserAuthz, requested_by: APIUser, user_id: str | MemberQualifier, project_id: str
) -> ProjectAuthorizationRemoved:
    """Transform project authz removal to message queue message."""
    return ProjectAuthorizationRemoved(
        projectId=project_id,
        userId=str(user_id),
    )


@dataclass
class SQLProjectAuthorizer:
    """Adapter to store authorization data for projects in SQL."""

    session_maker: Callable[..., AsyncSession] = field(init=True)
    message_queue: IMessageQueue = field(init=True)
    event_repo: EventRepository = field(init=True)

    async def has_permission(self, user: APIUser, project_id: str, scope: Scope) -> bool:
        """Whether the permissions granted to the user for the project match the access level."""
        stmt = select(ProjectUserAuthz).where(ProjectUserAuthz.project_id == project_id)
        if not user.is_admin:
            # NOTE: the specific user should have the required access level OR
            # the user field should be NULL in the db (which means it applies to users)
            stmt = stmt.where(scope.sql_access_test()).where(
                or_(ProjectUserAuthz.user_id == user.id, ProjectUserAuthz.user_id.is_(None))
            )
        async with self.session_maker() as session:
            res = await session.execute(stmt)
            permission = res.scalars().first()
        return permission is not None

    async def has_role(self, user: APIUser, project_id: str, role: Role) -> bool:
        """Check if the user has the specific member type on a project."""
        stmt = select(ProjectUserAuthz).where(ProjectUserAuthz.project_id == project_id)
        if not user.is_admin:
            # NOTE: the specific user should have the required access level OR
            # the user field should be NULL in the db (which means it applies to users)
            stmt = stmt.where(or_(ProjectUserAuthz.user_id == user.id, ProjectUserAuthz.user_id.is_(None))).where(
                role.sql_access_test()
            )
        async with self.session_maker() as session:
            res = await session.execute(stmt)
            permission = res.scalars().first()
        return permission is not None

    async def get_project_qualifier_and_users(
        self, requested_by: APIUser, project_id: str, scope: Scope
    ) -> tuple[MemberQualifier, list[str]]:
        """Which users have the specific permission on a project considering member qualifier."""
        users = await self._get_project_users_full(requested_by=requested_by, project_id=project_id, scope=scope)
        users_list = [u.user_id for u in users]

        if len(users_list) == 0:
            return MemberQualifier.NONE, []
        elif None in users_list:
            return MemberQualifier.ALL, []
        else:
            return MemberQualifier.SOME, users_list  # type: ignore[return-value]

    async def get_project_users(self, requested_by: APIUser, project_id: str, scope: Scope) -> list[ProjectMember]:
        """Get users that have explicit access to a project."""
        users = await self._get_project_users_full(requested_by=requested_by, project_id=project_id, scope=scope)

        return [ProjectMember(role=Role(u.role), user_id=u.user_id) for u in users if u.user_id is not None]

    async def _get_project_users_full(
        self, requested_by: APIUser, project_id: str, scope: Scope
    ) -> list[ProjectUserAuthz]:
        """Get all users of a project."""
        async with self.session_maker() as session:
            if not requested_by.is_authenticated:
                raise errors.Unauthorized(message="Unauthenticated users cannot query permissions of other users.")
            if not requested_by.is_admin:
                requested_by_owner = await self.has_role(requested_by, project_id, Role.OWNER)
                if not requested_by_owner:
                    raise errors.Unauthorized(message="Only the owner of the project can see who has access to it.")
            stmt = (
                select(ProjectUserAuthz)
                .distinct()
                .where(ProjectUserAuthz.project_id == project_id)
                .where(scope.sql_access_test())
            )
            res = await session.execute(stmt)
            users = res.scalars().all()

            return cast(list[ProjectUserAuthz], users)

    async def get_user_projects(self, requested_by: APIUser, user_id: str | MemberQualifier, scope: Scope) -> list[str]:
        """Which project IDs can a specific user access at the designated access level."""
        if not requested_by.is_authenticated and user_id != MemberQualifier.ALL:
            raise errors.Unauthorized(message="Unauthenticated users cannot query permissions of specific users.")
        if requested_by.is_authenticated and not requested_by.is_admin and user_id != requested_by.id:
            raise errors.Unauthorized(message="Users can access only their own permission information")
        stmt = select(ProjectUserAuthz.project_id).distinct().where(scope.sql_access_test())
        if isinstance(user_id, MemberQualifier):
            if user_id != MemberQualifier.ALL:
                raise errors.ValidationError(
                    message="When checking user permissions the only "
                    f"acceptable qualifier is ALL, you provided {user_id}"
                )
            stmt = stmt.where(user_id.sql_access_test([]))
        elif requested_by.is_admin:
            pass
        else:
            stmt = stmt.where(
                or_(MemberQualifier.SOME.sql_access_test([user_id]), MemberQualifier.ALL.sql_access_test([]))
            )
        async with self.session_maker() as session:
            res = await session.execute(stmt)
            projects = res.scalars().all()
        return [i for i in projects]

    @with_db_transaction
    @dispatch_message(create_project_auth_added_message)
    async def add_user(
        self, session: AsyncSession, requested_by: APIUser, user_id: str | MemberQualifier, project_id: str, role: Role
    ):
        """Add a user to the project."""
        if not requested_by.is_authenticated:
            raise errors.Unauthorized(message="Unauthenticated users cannot add users.")
        if isinstance(user_id, MemberQualifier) and user_id != MemberQualifier.ALL:
            raise errors.ValidationError(message=f"Valid qualifier for adding users is only ALL, received {user_id}.")
        if not requested_by.is_admin:
            can_add_users = await self.has_role(requested_by, project_id, Role.OWNER)
            if not can_add_users:
                raise errors.Unauthorized(
                    message=f"The user with ID {requested_by.id} cannot add users to project with ID {project_id}",
                    detail=f"Only users with role {Role.OWNER} can do this.",
                )
        user_id = (  # type: ignore[arg-type]
            None  # type: ignore[assignment]
            if isinstance(user_id, MemberQualifier) and user_id == MemberQualifier.ALL
            else user_id
        )
        authz = ProjectUserAuthz(
            project_id=project_id,
            role=role.value,
            user_id=user_id,  # type: ignore
        )
        session.add(authz)
        return authz

    @with_db_transaction
    @dispatch_message(create_project_auth_updated_message)
    async def update_or_add_user(
        self, session: AsyncSession, requested_by: APIUser, user_id: str | MemberQualifier, project_id: str, role: Role
    ):
        """Update user's role or add user if it doesn't exist."""
        if not requested_by.is_authenticated:
            raise errors.Unauthorized(message="Unauthenticated users cannot update users.")
        if isinstance(user_id, MemberQualifier):
            raise errors.ValidationError(message=f"Cannot use qualifiers as user ID: {user_id}.")
        if not requested_by.is_admin:
            can_update_users = await self.has_role(requested_by, project_id, Role.OWNER)
            if not can_update_users:
                raise errors.Unauthorized(
                    message=f"The user with ID {requested_by.id} cannot update users of project with ID {project_id}",
                    detail=f"Only users with role {Role.OWNER} can do this.",
                )
        stmt = select(ProjectUserAuthz).where(
            and_(ProjectUserAuthz.project_id == project_id, ProjectUserAuthz.user_id == user_id)
        )
        result = await session.execute(stmt)
        user_authz = result.scalars().first()
        if not user_authz:
            return await self.add_user(requested_by=requested_by, user_id=user_id, project_id=project_id, role=role)

        user_authz.role = role.value
        return user_authz

    @with_db_transaction
    @dispatch_message(create_project_auth_removed_message)
    async def delete_user(
        self, session: AsyncSession, requested_by: APIUser, user_id: str | MemberQualifier, project_id: str
    ):
        """Delete a member from a project."""
        if not requested_by.is_authenticated:
            raise errors.Unauthorized(message="Unauthenticated users cannot delete users.")
        if isinstance(user_id, MemberQualifier):
            raise errors.ValidationError(message=f"Cannot use qualifiers as user ID: {user_id}.")
        if not requested_by.is_admin:
            can_delete_users = await self.has_role(requested_by, project_id, Role.OWNER)
            if not can_delete_users:
                raise errors.Unauthorized(
                    message=f"The user with ID {requested_by.id} cannot delete users of project with ID {project_id}",
                    detail=f"Only users with role {Role.OWNER} can do this.",
                )
        stmt = delete(ProjectUserAuthz).where(
            and_(ProjectUserAuthz.project_id == project_id, ProjectUserAuthz.user_id == user_id)
        )
        await session.execute(stmt)

    @with_db_transaction
    @dispatch_message(create_project_auth_added_message)
    async def create_project(
        self, session: AsyncSession, requested_by: APIUser, project_id: str, public_project: bool = False
    ):
        """Insert the project in the authorization table."""
        if not requested_by.is_authenticated:
            raise errors.Unauthorized(message="Unauthenticated users cannot create projects.")
        res = await session.execute(
            select(ProjectUserAuthz.project_id).where(ProjectUserAuthz.project_id == project_id)
        )
        project_exists = res.scalars().first()
        if project_exists:
            raise errors.ValidationError(
                message="Cannot create a project if it already exists in the permissions database"
            )
        if public_project:
            session.add(ProjectUserAuthz(project_id=project_id, role=Role.MEMBER.value, user_id=None))
        proj_auth = ProjectUserAuthz(project_id=project_id, role=Role.OWNER.value, user_id=requested_by.id)
        session.add(proj_auth)
        return proj_auth

    async def update_project_visibility(self, requested_by: APIUser, project_id: str, public_project: bool):
        """Change project's qualifier accordingly."""
        async with self.session_maker() as session, session.begin():
            if not requested_by.is_authenticated:
                raise errors.Unauthorized(message="Unauthenticated users cannot update projects.")
            if not requested_by.is_admin:
                requested_by_owner = await self.has_role(requested_by, project_id, Role.OWNER)
                if not requested_by_owner:
                    raise errors.Unauthorized(message="Only the owner of the project can update a project.")

            if public_project:
                stmt = (
                    select(ProjectUserAuthz.user_id)
                    .where(ProjectUserAuthz.project_id == project_id)
                    .where(ProjectUserAuthz.user_id.is_(None))
                )
                result = await session.execute(stmt)
                rows = result.scalars().all()
                if rows:
                    # There already exists a row that shows the project is public
                    return

                session.add(ProjectUserAuthz(project_id=project_id, role=Role.MEMBER.value, user_id=None))
            else:
                del_stmt = delete(ProjectUserAuthz).where(
                    and_(ProjectUserAuthz.project_id == project_id, ProjectUserAuthz.user_id.is_(None))
                )
                await session.execute(del_stmt)

    async def delete_project(self, requested_by: APIUser, project_id: str):
        """Delete all instances of the project in the authorization table."""
        if not requested_by.is_authenticated:
            raise errors.Unauthorized(message="Unauthenticated users cannot delete projects.")
        async with self.session_maker() as session, session.begin():
            del_stmt = delete(ProjectUserAuthz).where(ProjectUserAuthz.project_id == project_id)
            if not requested_by.is_admin:
                user_is_owner = self.has_role(requested_by, project_id, Role.OWNER)
                if not user_is_owner:
                    raise errors.Unauthorized(
                        message="Only the owner or admin can remove a project from the permissions."
                    )
            await session.execute(del_stmt)
