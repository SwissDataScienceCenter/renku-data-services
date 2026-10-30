"""Scheduler for session runners."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from renku_data_services.app_config import logging
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER
from renku_data_services.k8s.db import K8sDbCache
from renku_data_services.k8s.models import (
    K8sObjectMeta,
)
from renku_data_services.notebooks.constants import AMALTHEA_SESSION_GVK
from renku_data_services.notebooks.crs import AmaltheaSessionV1Alpha1
from renku_data_services.session_runners import models
from renku_data_services.session_runners.db import UserSessionRunnersSchedulingRepository

logger = logging.getLogger(__name__)


RUNNER_LAST_CONTACT_TIMEOUT: Final[timedelta] = timedelta(minutes=5)


class UserSessionRunnerScheduler:
    """Scheduler for user-scoped session runners."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        scheduling_repo: UserSessionRunnersSchedulingRepository,
        k8s_db_cache: K8sDbCache,
    ) -> None:
        self.session_maker = session_maker
        self.scheduling_repo = scheduling_repo
        self.k8s_db_cache = k8s_db_cache

    async def reconcile(self) -> None:
        """Reconcile user-scoped session runners with the state of Amalthea sessions in Kubernetes."""
        async with self.session_maker() as session, session.begin():
            # Update runner statuses: mark runners who lost contact as not ready
            runners_ready = self.scheduling_repo.get_all_runners(
                session=session, filter_status=models.RunnerStatus.ready
            )
            now = datetime.now(tz=UTC)
            async for runner in runners_ready:
                if runner.last_contact is None or (now - runner.last_contact) > RUNNER_LAST_CONTACT_TIMEOUT:
                    logger.info(f"Marking runner {runner.id} as not ready.")
                    await self.scheduling_repo.update_runner_status(
                        session=session, runner_id=runner.id, status=models.RunnerStatus.not_ready
                    )

            remote_sessions = self.scheduling_repo.get_all_remote_sessions(session=session)
            async for remote_session in remote_sessions:
                k8s_session = await self._get_k8s_session(session_id=remote_session.session_id)

                # Hande session shut down
                if k8s_session is None:
                    await self.scheduling_repo.delete_remote_session(
                        session=session, renku_session_id=remote_session.session_id
                    )
                    logger.info(f"Removed remote session {remote_session.session_id}.")
                    continue

                # Handle sessions which need a runner
                if remote_session.runner_id is None:
                    await self._pick_runner(session=session, remote_session=remote_session)

    async def _get_k8s_session(self, session_id: str) -> AmaltheaSessionV1Alpha1 | None:
        """Get an Amalthea session from the Kubernetes cache."""
        meta = K8sObjectMeta(
            name=session_id,
            namespace=None,
            cluster=DEFAULT_K8S_CLUSTER,
            gvk=AMALTHEA_SESSION_GVK,
            user_id=None,
        )
        k8s_obj = await self.k8s_db_cache.get(meta)
        if k8s_obj is None:
            return None
        return AmaltheaSessionV1Alpha1.model_validate(k8s_obj.manifest)

    async def _pick_runner(self, session: AsyncSession, remote_session: models.RemoteUserSession) -> ULID | None:
        """Pick a runner for a given remote session."""
        runners = self.scheduling_repo.get_viable_runners(session=session, renku_session_id=remote_session.session_id)
        async for runner in runners:
            # TODO: any other check on the runner?
            remote_session = await self.scheduling_repo.update_remote_session_set_runner(
                session=session, renku_session_id=remote_session.session_id, runner_id=runner.id
            )
            logger.info(f"Assigned runner {remote_session.runner_id} to session {remote_session.session_id}.")
            return remote_session.runner_id

        logger.warning(f"Could not assign a runner to session {remote_session.session_id}.")
        return None
