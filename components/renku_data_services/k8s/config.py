"""Base config for k8s."""

import os

import kr8s
import yaml

from renku_data_services.app_config import logging
from renku_data_services.crc.db import ClusterRepository
from renku_data_services.k8s import models as k8s_models
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER

logger = logging.getLogger(__name__)


class KubeConfig:
    """Wrapper around kube config to get a kr8s api."""

    def __init__(
        self,
        kubeconfig: str | None = None,
        current_context_name: str | None = None,
        ns: str | None = None,
        sa: str | None = None,
        url: str | None = None,
    ) -> None:
        self._kubeconfig = kubeconfig
        self._ns = ns
        self._current_context_name = current_context_name
        self._sa = sa
        self._url = url

    def _sync_api(self) -> kr8s.Api | kr8s._AsyncApi:
        return kr8s.api(
            kubeconfig=self._kubeconfig,
            namespace=self._ns,
            context=self._current_context_name,
        )

    def _async_api(self) -> kr8s.asyncio.Api:
        """Create an async api client from sync code.

        Kr8s cannot return an AsyncAPI instance from sync code, and we can't easily make all our config code async,
        so this method is a direct copy of the kr8s sync client code, just that it returns an async client.
        """
        ret = kr8s._async_utils.run_sync(kr8s.asyncio.api)(
            url=self._url,
            kubeconfig=self._kubeconfig,
            serviceaccount=self._sa,
            namespace=self._ns,
            context=self._current_context_name,
            _asyncio=True,  # This is the only line that is different from kr8s code
        )
        assert isinstance(ret, kr8s.asyncio.Api)
        return ret

    def api(self, _async: bool = True) -> kr8s.Api | kr8s._AsyncApi:
        """Instantiate the Kr8s Api object based on the configuration."""
        if _async:
            return self._async_api()
        else:
            return self._sync_api()


class KubeConfigEnv(KubeConfig):
    """Get a kube config from the environment."""

    def __init__(self) -> None:
        super().__init__(ns=os.environ.get("K8S_NAMESPACE", "default"))


class KubeConfigYaml(KubeConfig):
    """Get a kube config from a yaml file."""

    def __init__(self, kubeconfig: str) -> None:
        super().__init__(kubeconfig=kubeconfig)

        with open(kubeconfig) as stream:
            _conf = yaml.safe_load(stream)

        self._current_context_name = _conf.get("current-context", None)
        if self._current_context_name is not None:
            for context in _conf.get("contexts", []):
                name = context.get("name", None)
                inner = context.get("context", None)
                if inner is not None and name is not None and name == self._current_context_name:
                    self._ns = inner.get("namespace", None)
                    break


async def get_clusters(
    kube_conf_root_dir: str, namespace: str, api: kr8s.asyncio.Api, cluster_rp: ClusterRepository
) -> list[k8s_models.Cluster]:
    """Get all clusters accessible to the application."""

    clusters = [k8s_models.Cluster(id=DEFAULT_K8S_CLUSTER, namespace=namespace, api=api)]

    if not os.path.exists(kube_conf_root_dir):
        logger.warning(f"Cannot open directory '{kube_conf_root_dir}', ignoring kube configs...")
        return clusters

    async for db_cluster in cluster_rp.select_all():
        filename = db_cluster.config_name
        try:
            kube_config = KubeConfigYaml(f"{kube_conf_root_dir}/{filename}")
            cluster = k8s_models.Cluster(
                id=db_cluster.id,
                namespace=kube_config.api().namespace,
                api=kube_config.api(),
            )
            clusters.append(cluster)
            logger.info(f"Successfully loaded Kubernetes config: '{kube_conf_root_dir}/{filename}'")
        except Exception as e:
            logger.warning(f"Failed while loading '{kube_conf_root_dir}/{filename}', ignoring kube config. Error: {e}")

    return clusters
