"""Scheduler for session runners."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services.app_config import logging
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER
from renku_data_services.k8s.db import K8sDbCache
from renku_data_services.k8s.models import (
    K8sObjectMeta,
)
from renku_data_services.notebooks.constants import AMALTHEA_SESSION_GVK
from renku_data_services.notebooks.crs import AmaltheaSessionV1Alpha1
from renku_data_services.session_runners import models
from renku_data_services.session_runners.db import SessionRunnersSchedulingRepository

logger = logging.getLogger(__name__)


RUNNER_LAST_CONTACT_TIMEOUT: Final[timedelta] = timedelta(minutes=5)


class SessionRunnerScheduler:
    """Scheduler for session runners."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        session_runners_scheduling_repo: SessionRunnersSchedulingRepository,
        k8s_db_cache: K8sDbCache,
    ) -> None:
        self.session_maker = session_maker
        self.session_runners_scheduling_repo = session_runners_scheduling_repo
        self.k8s_db_cache = k8s_db_cache

    async def reconcile(self) -> None:
        """Reconcile session runners and Kubernetes state."""
        async with self.session_maker() as session, session.begin():
            # Update runner statuses: mark runners who lost contact as not ready
            runners_ready = self.session_runners_scheduling_repo.get_all_runners(
                session=session, filter_status=models.RunnerStatus.ready
            )
            now = datetime.now(tz=UTC)
            async for runner in runners_ready:
                if runner.last_contact is None or (runner.last_contact - now) > RUNNER_LAST_CONTACT_TIMEOUT:
                    logger.info(f"[SESSION RUNNERS] Marking runner {runner.id} as not ready.")
                    await self.session_runners_scheduling_repo.update_runner_status(
                        session=session, runner_id=runner.id, status=models.RunnerStatus.not_ready
                    )

            assigned_sessions = self.session_runners_scheduling_repo.get_all_assigned_sessions(session=session)
            async for assigned_session in assigned_sessions:
                k8s_session = await self._get_k8s_session(session_id=assigned_session.session_id)

                # Hande session shut down
                if k8s_session is None:
                    await self.session_runners_scheduling_repo.delete_assigned_session(
                        session=session, renku_session_id=assigned_session.session_id
                    )
                    logger.info(f"[SESSION RUNNERS] Deleted assigned session {assigned_session.session_id}.")
                    continue

                # TODO (?): handle k8s state update (incl. Hibernated: true)

                # Handle sessions which need a runner
                if assigned_session.runner_id is None:
                    await self._pick_runner(session=session, assigned_session=assigned_session)

    async def _get_k8s_session(self, session_id: str) -> AmaltheaSessionV1Alpha1 | None:
        """Get a session from the Kubernetes cache."""
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

    async def _pick_runner(self, session: AsyncSession, assigned_session: models.AssignedSession) -> None:
        """Pick a runner for a given session."""
        runners = self.session_runners_scheduling_repo.get_viable_runners(
            session=session, renku_session_id=assigned_session.session_id
        )
        async for runner in runners:
            # TODO: any other check on the runner?
            assigned_session = await self.session_runners_scheduling_repo.update_assigned_session_set_runner(
                session=session, renku_session_id=assigned_session.session_id, runner_id=runner.id
            )
            logger.info(
                f"[SESSION RUNNERS] Assigned runner {assigned_session.runner_id} "
                f"to session {assigned_session.session_id}."
            )
            return

        logger.warning(f"[SESSION RUNNERS] Could not assign a runner to session {assigned_session.session_id}.")
