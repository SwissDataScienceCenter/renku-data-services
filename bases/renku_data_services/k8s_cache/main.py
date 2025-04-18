"""The entrypoint for the k8s cache service."""

import asyncio
import logging

import kr8s

from renku_data_services.k8s.models import Cluster, ClusterId
from renku_data_services.k8s_cache.config import Config
from renku_data_services.k8s_watcher import K8sWatcher, k8s_object_handler
from renku_data_services.notebooks.constants import AMALTHEA_SESSION_KIND, JUPYTER_SESSION_KIND


async def main() -> None:
    """K8s cache entrypoint."""

    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
    config = Config.from_env()

    kr8s_api = await kr8s.asyncio.api()
    clusters = [Cluster(id=ClusterId("renkulab"), namespace=config.k8s.renku_namespace, api=kr8s_api)]

    watcher = K8sWatcher(
        handler=k8s_object_handler(config.k8s_cache),
        clusters={c.id: c for c in clusters},
        kinds=[AMALTHEA_SESSION_KIND, JUPYTER_SESSION_KIND],
    )
    await watcher.start()
    logging.info("started watching resources")
    # create file for liveness probe
    with open("/tmp/cache_ready", "w") as f:  # nosec B108
        f.write("ready")
    await watcher.wait()


if __name__ == "__main__":
    asyncio.run(main())
