"""Adapters for session database classes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.authz.authz import IProjectAuthorizer
from renku_data_services.authz.models import MemberQualifier, Scope
from renku_data_services.session import apispec, models
from renku_data_services.session import orm as schemas
from renku_data_services.session.apispec import EnvironmentKind


class SessionRepository:
    """Repository for sessions."""

    def __init__(self, session_maker: Callable[..., AsyncSession], project_authz: IProjectAuthorizer):
        self.session_maker = session_maker
        self.project_authz: IProjectAuthorizer = project_authz

    async def get_environments(self) -> list[models.SessionEnvironment]:
        """Get all session environments from the database."""
        async with self.session_maker() as session:
            res = await session.scalars(select(schemas.SessionEnvironmentORM))
            environments = res.all()
            return [e.dump() for e in environments]

    async def get_environment(self, environment_id: str) -> models.SessionEnvironment:
        """Get one session environment from the database."""
        async with self.session_maker() as session:
            res = await session.scalars(
                select(schemas.SessionEnvironmentORM).where(schemas.SessionEnvironmentORM.id == environment_id)
            )
            environment = res.one_or_none()
            if environment is None:
                raise errors.MissingResourceError(
                    message=f"Session environment with id '{environment_id}' \
                        does not exist or you do not have access to it."
                )
            return environment.dump()

    async def insert_environment(
        self,
        user: base_models.APIUser,
        new_environment: apispec.EnvironmentPost,
    ) -> models.SessionEnvironment:
        """Insert a new session environment."""
        if user.id is None or not user.is_admin:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")

        environment_model = models.NewSessionEnvironment(
            name=new_environment.name,
            description=new_environment.description,
            container_image=new_environment.container_image,
            created_by=models.Member(id=user.id),
            creation_date=datetime.now(timezone.utc).replace(microsecond=0),
        )
        environment = schemas.SessionEnvironmentORM.load(environment_model)

        async with self.session_maker() as session:
            async with session.begin():
                session.add(environment)
                return environment.dump()

    async def update_environment(
        self, user: base_models.APIUser, environment_id: str, **kwargs
    ) -> models.SessionEnvironment:
        """Update a session environment entry."""
        if not user.is_admin:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session:
            async with session.begin():
                res = await session.scalars(
                    select(schemas.SessionEnvironmentORM).where(schemas.SessionEnvironmentORM.id == environment_id)
                )
                environment = res.one_or_none()
                if environment is None:
                    raise errors.MissingResourceError(
                        message=f"Session environment with id '{environment_id}' does not exist."
                    )

                for key, value in kwargs.items():
                    # NOTE: Only ``name``, ``description``, and ``container_image`` can be edited
                    if key in ["name", "description", "container_image"]:
                        setattr(environment, key, value)

                return environment.dump()

    async def delete_environment(self, user: base_models.APIUser, environment_id: str) -> None:
        """Delete a session environment entry."""
        if not user.is_admin:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session:
            async with session.begin():
                res = await session.scalars(
                    select(schemas.SessionEnvironmentORM).where(schemas.SessionEnvironmentORM.id == environment_id)
                )
                environment = res.one_or_none()

                if environment is None:
                    return

                await session.delete(environment)

    async def get_launchers(self, user: base_models.APIUser) -> list[models.SessionLauncher]:
        """Get all session launchers visible for a specific user from the database."""
        user_id: str | MemberQualifier = (
            user.id if user.is_authenticated and user.id is not None else MemberQualifier.ALL
        )
        project_ids = await self.project_authz.get_user_projects(requested_by=user, user_id=user_id, scope=Scope.READ)

        async with self.session_maker() as session:
            res = await session.scalars(
                select(schemas.SessionLauncherORM)
                .where(schemas.SessionLauncherORM.project_id.in_(project_ids))
                .order_by(schemas.SessionLauncherORM.creation_date.desc())
            )
            launcher = res.all()
            return [item.dump() for item in launcher]

    async def get_project_launchers(self, user: base_models.APIUser, project_id: str) -> list[models.SessionLauncher]:
        """Get all session launchers in a project from the database."""
        authorized = await self.project_authz.has_permission(user=user, project_id=project_id, scope=Scope.READ)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        async with self.session_maker() as session:
            res = await session.scalars(
                select(schemas.SessionLauncherORM)
                .where(schemas.SessionLauncherORM.project_id == project_id)
                .order_by(schemas.SessionLauncherORM.creation_date.desc())
            )
            launcher = res.all()
            return [item.dump() for item in launcher]

    async def get_launcher(self, user: base_models.APIUser, launcher_id: str) -> models.SessionLauncher:
        """Get one session launcher from the database."""
        async with self.session_maker() as session:
            res = await session.scalars(
                select(schemas.SessionLauncherORM).where(schemas.SessionLauncherORM.id == launcher_id)
            )
            launcher = res.one_or_none()

            authorized = (
                await self.project_authz.has_permission(user=user, project_id=launcher.project_id, scope=Scope.READ)
                if launcher is not None
                else False
            )
            if not authorized or launcher is None:
                raise errors.MissingResourceError(
                    message=f"Session launcher with id '{launcher_id}' does not exist or you do not have access to it."
                )

            return launcher.dump()

    async def insert_launcher(
        self, user: base_models.APIUser, new_launcher: apispec.LauncherPost
    ) -> models.SessionLauncher:
        """Insert a new session launcher."""
        if not user.is_authenticated or user.id is None:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")

        project_id = new_launcher.project_id
        authorized = await self.project_authz.has_permission(user=user, project_id=project_id, scope=Scope.READ)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        async with self.session_maker() as session:
            async with session.begin():
                res = await session.scalars(select(schemas.ProjectORM).where(schemas.ProjectORM.id == project_id))
                project = res.one_or_none()
                if project is None:
                    raise errors.MissingResourceError(
                        message=f"Project with id '{project_id}' does not exist or you do not have access to it."
                    )

                environment_id = new_launcher.environment_id
                if environment_id is not None:
                    res = await session.scalars(
                        select(schemas.SessionEnvironmentORM).where(schemas.SessionEnvironmentORM.id == environment_id)
                    )
                    environment = res.one_or_none()
                    if environment is None:
                        raise errors.MissingResourceError(
                            message=f"Session environment with id '{environment_id}' \
                                does not exist or you do not have access to it."
                        )

                launcher_model = models.NewSessionLauncher(
                    name=new_launcher.name,
                    project_id=new_launcher.project_id,
                    description=new_launcher.description,
                    environment_kind=new_launcher.environment_kind,
                    environment_id=new_launcher.environment_id,
                    container_image=new_launcher.container_image,
                    created_by=models.Member(id=user.id),
                    creation_date=datetime.now(timezone.utc).replace(microsecond=0),
                )

                models.NewSessionLauncher.model_validate(launcher_model)

                launcher = schemas.SessionLauncherORM.load(launcher_model)
                return launcher.dump()

    async def update_launcher(self, user: base_models.APIUser, launcher_id: str, **kwargs) -> models.SessionLauncher:
        """Update a session launcher entry."""
        if not user.is_authenticated or user.id is None:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session:
            async with session.begin():
                res = await session.scalars(
                    select(schemas.SessionLauncherORM).where(schemas.SessionLauncherORM.id == launcher_id)
                )
                launcher = res.one_or_none()
                if launcher is None:
                    raise errors.MissingResourceError(
                        message=f"Session launcher with id '{launcher_id}' \
                            does not exist or you do not have access to it."
                    )

                authorized = await self.project_authz.has_permission(
                    user=user, project_id=launcher.project_id, scope=Scope.WRITE
                )
                if not authorized:
                    raise errors.Unauthorized(message="You do not have the required permissions for this operation.")

                for key, value in kwargs.items():
                    # NOTE: Only ``name``, ``description``, ``environment_kind``,
                    #       ``environment_id`` and ``container_image`` can be edited.
                    if key in ["name", "description", "environment_kind", "environment_id", "container_image"]:
                        setattr(launcher, key, value)

                if launcher.environment_kind == EnvironmentKind.global_environment:
                    launcher.container_image = None
                if launcher.environment_kind == EnvironmentKind.container_image:
                    launcher.environment = None

                launcher_model = launcher.dump()
                models.SessionLauncher.model_validate(launcher_model)

                return launcher_model

    async def delete_launcher(self, user: base_models.APIUser, launcher_id: str) -> None:
        """Delete a session launcher entry."""
        if not user.is_admin:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session:
            async with session.begin():
                res = await session.scalars(
                    select(schemas.SessionLauncherORM).where(schemas.SessionLauncherORM.id == launcher_id)
                )
                launcher = res.one_or_none()

                if launcher is None:
                    return

                await session.delete(launcher)

    # async def get_sessions(self, user: base_models.APIUser) -> list[models.Session]:
    #     """Get all sessions from the database."""
    #     user_id = user.id if user.is_authenticated else MemberQualifier.ALL
    #     # NOTE: without the line below mypy thinks user_id can be None
    #     user_id = user_id if user_id is not None else MemberQualifier.ALL
    #     project_ids = await self.project_authz.get_user_projects(requested_by=user, user_id=user_id, scope=Scope.READ)

    #     async with self.session_maker() as session:
    #         statement = select(schemas.SessionORM)
    #         statement = statement.where(schemas.SessionORM.project_id.in_(project_ids))
    #         statement = statement.order_by(schemas.SessionORM.creation_date.desc())
    #         result = await session.execute(statement)
    #         sessions_orm = result.scalars().all()

    #         return [p.dump() for p in sessions_orm]

    # async def get_session(self, user: base_models.APIUser, session_id: str) -> models.Session:
    #     """Get one session from the database."""
    #     async with self.session_maker() as session:
    #         statement = select(schemas.SessionORM).where(schemas.SessionORM.id == session_id)
    #         result = await session.execute(statement)
    #         session_orm = result.scalars().first()

    #         if session_orm is None:
    #             raise errors.MissingResourceError(message=f"Session with id '{session_id}' does not exist.")

    #         authorized = await self.project_authz.has_permission(
    #             user=user, project_id=session_orm.project_id, scope=Scope.READ
    #         )
    #         if not authorized:
    #             raise errors.MissingResourceError(
    #                 message=f"Session with id '{session_id}' does not exist or you do not have access to it."
    #             )

    #         return session_orm.dump()

    # async def insert_session(self, user: base_models.APIUser, session: models.Session) -> models.Session:
    #     """Insert a new session entry."""
    #     authorized = await self.project_authz.has_permission(
    #         user=user, project_id=session.project_id, scope=Scope.WRITE
    #     )
    #     if not authorized:
    #         raise errors.MissingResourceError(
    #             message=f"Project with id '{session.project_id}' does not exist or you do not have access to it."
    #         )

    #     session_orm = schemas.SessionORM.load(session)
    #     session_orm.creation_date = datetime.now(timezone.utc).replace(microsecond=0)
    #     session_orm.created_by = user.id

    #     async with self.session_maker() as database_session:
    #         async with database_session.begin():
    #             database_session.add(session_orm)

    #             if session_orm.id is None:
    #                 raise errors.BaseError(detail="The created session does not have an ID but it should.")

    #     return session_orm.dump()

    # async def update_session(self, user: base_models.APIUser, session_id: str, **payload) -> models.Session:
    #     """Update a session entry."""
    #     async with self.session_maker() as session:
    #         async with session.begin():
    #             result = await session.execute(select(schemas.SessionORM).where(schemas.SessionORM.id == session_id))
    #             sessions_orm = result.one_or_none()

    #             if sessions_orm is None:
    #                 raise errors.MissingResourceError(
    #                     message=f"Session with id '{session_id}' does not exist or you do not have access to it."
    #                 )
    #             session_orm = sessions_orm[0]

    #             authorized = await self.project_authz.has_permission(
    #                 user=user, project_id=session_orm.project_id, scope=Scope.WRITE
    #             )
    #             if not authorized:
    #                 raise errors.MissingResourceError(
    #                     message=f"Session with id '{session_id}' does not exist or you do not have access to it."
    #                 )

    #             for key, value in payload.items():
    #                 # NOTE: Only ``name``, ``description``, and ``environment_id`` can be edited
    #                 if key in ["name", "description", "environment_id"]:
    #                     setattr(session_orm, key, value)

    #             # NOTE: Triggers validation before the transaction saves data
    #             return session_orm.dump()

    # async def delete_session(self, user: base_models.APIUser, session_id: str) -> None:
    #     """Delete a cloud session entry."""
    #     async with self.session_maker() as session:
    #         async with session.begin():
    #             result = await session.execute(select(schemas.SessionORM).where(schemas.SessionORM.id == session_id))
    #             sessions_orm = result.one_or_none()

    #             if sessions_orm is None:
    #                 return
    #             session_orm = sessions_orm[0]

    #             authorized = await self.project_authz.has_permission(
    #                 user=user, project_id=session_orm.project_id, scope=Scope.DELETE
    #             )
    #             if not authorized:
    #                 raise errors.MissingResourceError(
    #                     message=f"Session with id '{session_id}' does not exist or you do not have access to it."
    #                 )

    #             await session.delete(session_orm)
