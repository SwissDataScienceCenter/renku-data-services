"""The entrypoint for the k8s cache service."""

import asyncio
from typing import cast

import kr8s

from renku_data_services.k8s_cache.config import Config
from renku_data_services.k8s_watcher.db import Cluster, K8sWatcher, k8s_object_handler
from renku_data_services.k8s_watcher.models import ClusterId
from renku_data_services.notebooks.constants import AMALTHEA_SESSION_KIND, JUPYTER_SESSION_KIND

if __name__ == "__main__":
    config = Config.from_env()

    kr8s_api = cast(kr8s.Api, asyncio.run(kr8s.asyncio.api()))
    clusters = [Cluster(id=ClusterId("renkulab"), namespace=config.k8s.renku_namespace, api=kr8s_api)]

    watcher = K8sWatcher(
        handler=k8s_object_handler(config.k8s_cache),
        clusters={c.id: c for c in clusters},
        kinds=[AMALTHEA_SESSION_KIND, JUPYTER_SESSION_KIND],
    )
    watcher.start()
