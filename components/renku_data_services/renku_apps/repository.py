"""Repository for Renku apps backed by Knative Services in k8s."""

from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.app_config import logging
from renku_data_services.authz.authz import Authz, ResourceType
from renku_data_services.authz.models import Scope, Visibility
from renku_data_services.crc.db import ResourcePoolRepository
from renku_data_services.crc.models import ResourceClass
from renku_data_services.project.db import ProjectRepository
from renku_data_services.renku_apps import apispec
from renku_data_services.renku_apps.core import build_app
from renku_data_services.renku_apps.k8s_client import RenkuAppsK8sClient
from renku_data_services.renku_apps.models import App, AppRuntimeState
from renku_data_services.session.db import SessionRepository
from renku_data_services.session.models import SessionLauncher

logger = logging.getLogger(__name__)


def _app_not_found_message(app_name: str) -> str:
    """Build the message for a missing or inaccessible app."""
    return f"App with name '{app_name}' does not exist or you do not have access to it."


class RenkuAppsRepository:
    """Use-case-focused API for Renku apps, dispatching to k8s rather than SQL."""

    def __init__(
        self,
        authz: Authz,
        session_repo: SessionRepository,
        rp_repo: ResourcePoolRepository,
        project_repo: ProjectRepository,
        k8s_client: RenkuAppsK8sClient,
    ) -> None:
        self.authz = authz
        self.session_repo = session_repo
        self.rp_repo = rp_repo
        self.project_repo = project_repo
        self.k8s_client = k8s_client

    async def create_app(self, user: base_models.APIUser, launcher_id: ULID) -> App:
        """Launch a new app from a session launcher."""
        if not user.is_authenticated or user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        launcher = await self.session_repo.get_launcher(user, launcher_id)

        authorized = await self.authz.has_permission(user, ResourceType.project, launcher.project_id, Scope.WRITE)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{launcher.project_id}' does not exist or you do not have access to it."
            )

        resource_class: ResourceClass | None = None
        if launcher.resource_class_id is not None:
            resource_class = await self.rp_repo.get_resource_class(user, launcher.resource_class_id)

        project = await self.project_repo.get_project(user, launcher.project_id)
        if await self.k8s_client.get_app_deployment_for_project(project, launcher) is not None:
            raise errors.ConflictError(message=f"An app already exists for project '{launcher.project_id}'.")
        runtime_state = await self.k8s_client.create_app_deployment(launcher, resource_class, project)
        return build_app(launcher, runtime_state)

    async def get_app(self, user: base_models.APIUser, app_name: str) -> App:
        """Retrieve an app by its name."""
        runtime_state = await self.k8s_client.get_app_deployment(app_name)
        if runtime_state is None:
            raise errors.MissingResourceError(message=_app_not_found_message(app_name))

        launcher = await self.session_repo.get_launcher(user, runtime_state.launcher_id)
        return build_app(launcher, runtime_state)

    async def delete_app(self, user: base_models.APIUser, app_name: str) -> None:
        """Delete an app by its name."""
        if not user.is_authenticated or user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        runtime_state = await self.k8s_client.get_app_deployment(app_name)
        if runtime_state is None:
            logger.info(f"App with name {app_name} was not found.")
            return None

        launcher = await self.session_repo.get_launcher(user, runtime_state.launcher_id)

        authorized = await self.authz.has_permission(user, ResourceType.project, launcher.project_id, Scope.WRITE)
        if not authorized:
            raise errors.MissingResourceError(message=_app_not_found_message(app_name))

        await self.k8s_client.delete_app_deployment(app_name)
        logger.info(f"App with name {app_name} has been deleted.")
        return None

    async def delete_app_for_launcher(self, user: base_models.APIUser, launcher: SessionLauncher) -> None:
        """Delete the app deployment backing the given launcher, if one exists."""
        runtime_state = await self.k8s_client.get_app_deployment_for_launcher(launcher.id)
        if runtime_state is None:
            return None
        await self.delete_app(user, runtime_state.name)
        return None

    async def update_app(
        self,
        user: base_models.APIUser,
        app_name: str,
        state: apispec.AppState | None = None,
    ) -> App:
        """Update an app."""
        if not user.is_authenticated or user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        runtime_state = await self.k8s_client.get_app_deployment(app_name)
        if runtime_state is None:
            raise errors.MissingResourceError(message=_app_not_found_message(app_name))

        launcher = await self.session_repo.get_launcher(user, runtime_state.launcher_id)

        authorized = await self.authz.has_permission(user, ResourceType.project, launcher.project_id, Scope.WRITE)
        if not authorized:
            raise errors.MissingResourceError(message=_app_not_found_message(app_name))

        latest: AppRuntimeState = runtime_state
        if state == apispec.AppState.hibernated and not runtime_state.is_hibernated:
            latest = await self.k8s_client.hibernate_app_deployment(app_name)
        elif state == apispec.AppState.running and runtime_state.is_hibernated:
            project = await self.project_repo.get_project(user, launcher.project_id)
            if project.visibility != Visibility.PUBLIC:
                raise errors.ValidationError(message="This app cannot be resumed because its project is not public.")
            if launcher.resource_class_id is not None:
                resource_class = await self.rp_repo.get_resource_class(user, launcher.resource_class_id)
                await self.k8s_client.set_app_deployment_resources(app_name, resource_class)
            latest = await self.k8s_client.resume_app_deployment(app_name)

        return build_app(launcher, latest)

    async def hibernate_apps_for_project(self, project_id: ULID) -> None:
        """Hibernate every running app belonging to the given project."""
        async for runtime_state in self.k8s_client.list_app_deployments(project_id):
            if not runtime_state.is_hibernated:
                await self.k8s_client.hibernate_app_deployment(runtime_state.name)

    async def list_apps(self, user: base_models.APIUser, project_id: ULID | None = None) -> list[App]:
        """List all apps, optionally filtered by project."""

        apps: list[App] = []
        async for runtime_state in self.k8s_client.list_app_deployments(project_id):
            try:
                launcher = await self.session_repo.get_launcher(user, runtime_state.launcher_id)
            except errors.MissingResourceError:
                logger.warning(
                    f"Launcher with id '{runtime_state.launcher_id}' for app '{runtime_state.name}' was not found."
                )
                continue
            apps.append(build_app(launcher, runtime_state))
        return apps
