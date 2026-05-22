"""Repository for Renku apps backed by Knative Services in k8s."""

from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.authz.authz import Authz, ResourceType
from renku_data_services.authz.models import Scope
from renku_data_services.renku_apps.core import knative_service_to_app
from renku_data_services.renku_apps.k8s_client import RenkuAppsK8sClient
from renku_data_services.renku_apps.models import App
from renku_data_services.session.db import SessionRepository


class RenkuAppsRepository:
    """Use-case-focused API for Renku apps, dispatching to k8s rather than SQL."""

    def __init__(
        self,
        authz: Authz,
        session_repo: SessionRepository,
        k8s_client: RenkuAppsK8sClient,
    ) -> None:
        self.authz = authz
        self.session_repo = session_repo
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

        service = await self.k8s_client.create_app_deployment(launcher)
        return knative_service_to_app(launcher, service)

    async def get_app(self, user: base_models.APIUser, app_name: str) -> App:
        """Retrieve an app by its name."""
        service = await self.k8s_client.get_app_deployment(app_name)
        if service is None:
            raise errors.MissingResourceError(
                message=f"App with name '{app_name}' does not exist or you do not have access to it."
            )

        launcher = await self.session_repo.get_launcher(user, service.launcher_id)
        return knative_service_to_app(launcher, service)
