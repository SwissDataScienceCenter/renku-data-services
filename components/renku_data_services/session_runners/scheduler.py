"""Scheduler for session runners."""

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services.app_config import logging
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER
from renku_data_services.k8s.db import K8sDbCache
from renku_data_services.k8s.models import (
    K8sObjectMeta,
)
from renku_data_services.notebooks.constants import AMALTHEA_SESSION_GVK
from renku_data_services.notebooks.crs import AmaltheaSessionV1Alpha1
from renku_data_services.session_runners.db import SessionRunnersSchedulingRepository

logger = logging.getLogger(__name__)


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
            assigned_sessions = self.session_runners_scheduling_repo.get_all_assigned_sessions(session=session)
            async for assigned_session in assigned_sessions:
                k8s_session = await self._get_k8s_session(session_id=assigned_session.session_id)
                logger.warning(f"[SESSION RUNNERS] TODO: handle {assigned_session} <-> {k8s_session}")

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
