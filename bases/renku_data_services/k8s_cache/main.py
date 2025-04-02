"""The entrypoint for the k8s cache service."""

import kr8s

from renku_data_services.k8s_cache.config import Config
from renku_data_services.k8s_watcher.db import Cluster, K8sWatcher, k8s_object_handler
from renku_data_services.k8s_watcher.models import ClusterId
from renku_data_services.notebooks.crs import AmaltheaSessionV1Alpha1

if __name__ == "__main__":
    config = Config.from_env()

    kr8s_api = kr8s.api()
    clusters = [Cluster(id=ClusterId("renkulab"), namespace=config.k8s.renku_namespace, api=kr8s_api)]

    watcher = K8sWatcher(
        handler=k8s_object_handler(config.k8s_cache),
        clusters={c.id: c for c in clusters},
        kind=AmaltheaSessionV1Alpha1.kind,
    )
    watcher.start()
