"""Task definitions."""

from collections.abc import Generator
from dataclasses import dataclass
from pathlib import PurePosixPath

from renku_data_services.app_config import logging
from renku_data_services.base_models.core import InternalServiceAdmin
from renku_data_services.session.db import SessionRepository
from renku_data_services.session.models import EnvironmentImageSource, EnvironmentKind, UnsavedEnvironment


@dataclass(kw_only=True)
class SessionTasks:
    """Task definitions for sessions."""

    session_repo: SessionRepository

    async def initialize_session_environments_task(self, requested_by: InternalServiceAdmin) -> None:
        """Initialize session environments."""
        logger = logging.getLogger(self.__class__.__name__)

        # Skip this task if global session environments already exist
        existing_envs = await self.session_repo.get_environments()
        if existing_envs:
            logger.debug("Global session environments are already initialized.")
            return None

        for env in self._get_default_session_environments():
            try:
                await self.session_repo.insert_environment(user=requested_by, environment=env)
            except Exception as err:
                logger.error(f"Failed to create global environment with image {env.container_image} because {err}")

    @staticmethod
    def _get_default_session_environments() -> Generator[UnsavedEnvironment, None, None]:
        """Generates the default list of session environments."""
        prefix = "ghcr.io/swissdatasciencecenter/renku"
        package_variants = ["basic", "datascience"]
        frontend_variants = ["jupyterlab", "ttyd", "vscodium"]
        for pv in package_variants:
            for fv in frontend_variants:
                image = f"{prefix}/py-{pv}-{fv}"
                name = f"Python {pv} - {fv}".title()
                description = f"{pv.title()} python environment with {fv} as a frontend."
                yield SessionTasks._make_default_session_environment(
                    name=name, container_image=image, description=description
                )

    @staticmethod
    def _make_default_session_environment(
        name: str, container_image: str, description: str | None = None
    ) -> UnsavedEnvironment:
        """Create a default session environment with a given container image."""
        return UnsavedEnvironment(
            name=name,
            description=description or "Default global environment",
            container_image=container_image,
            default_url="/",
            port=8888,
            working_directory=PurePosixPath("/home/renku/work"),
            mount_directory=PurePosixPath("/home/renku/work"),
            uid=1000,
            gid=1000,
            environment_kind=EnvironmentKind.GLOBAL,
            environment_image_source=EnvironmentImageSource.image,
            args=None,
            command=None,
            is_archived=False,
            strip_path_prefix=False,
        )
