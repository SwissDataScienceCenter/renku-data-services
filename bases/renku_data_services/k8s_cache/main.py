"""The entrypoint for the k8s cache service."""

import asyncio

import kr8s

from renku_data_services.app_config import logging
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER
from renku_data_services.k8s.models import Cluster
from renku_data_services.k8s_cache.dependencies import DependencyManager
from renku_data_services.k8s_watcher import K8sWatcher, k8s_object_handler
from renku_data_services.notebooks.constants import AMALTHEA_SESSION_GVK, JUPYTER_SESSION_GVK
from renku_data_services.session.constants import BUILD_RUN_GVK, TASK_RUN_GVK

logger = logging.getLogger(__name__)


async def main() -> None:
    """K8s cache entrypoint."""

    dm = DependencyManager.from_env()

    kr8s_api = await kr8s.asyncio.api()
    clusters = [Cluster(id=DEFAULT_K8S_CLUSTER, namespace=dm.config.k8s.renku_namespace, api=kr8s_api)]

    kinds = [AMALTHEA_SESSION_GVK, JUPYTER_SESSION_GVK]
    if dm.config.image_builders.enabled:
        kinds.extend([BUILD_RUN_GVK, TASK_RUN_GVK])
    watcher = K8sWatcher(
        handler=k8s_object_handler(dm.k8s_cache, dm.metrics, rp_repo=dm.rp_repo),
        clusters={c.id: c for c in clusters},
        kinds=kinds,
        db_cache=dm.k8s_cache,
    )
    await watcher.start()
    logger.info("started watching resources")
    # create file for liveness probe
    with open("/tmp/cache_ready", "w") as f:  # nosec B108
        f.write("ready")
    await watcher.wait()


if __name__ == "__main__":
    asyncio.run(main())
