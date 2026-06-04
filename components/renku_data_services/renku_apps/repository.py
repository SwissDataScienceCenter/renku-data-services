"""Repository for Renku apps backed by Knative Services in k8s."""

from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.authz.authz import Authz, ResourceType
from renku_data_services.authz.models import Scope
from renku_data_services.crc.db import ResourcePoolRepository
from renku_data_services.crc.models import ResourceClass
from renku_data_services.project.db import ProjectRepository
from renku_data_services.renku_apps.core import build_app
from renku_data_services.renku_apps.k8s_client import RenkuAppsK8sClient
from renku_data_services.renku_apps.models import App
from renku_data_services.session.db import SessionRepository


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
            raise errors.MissingResourceError(
                message=f"App with name '{app_name}' does not exist or you do not have access to it."
            )

        launcher = await self.session_repo.get_launcher(user, runtime_state.launcher_id)
        return build_app(launcher, runtime_state)
