"""Base config for k8s."""

import os
from collections.abc import AsyncIterable, Awaitable

import aiofiles
import kr8s
import yaml

from renku_data_services.app_config import logging
from renku_data_services.crc.db import ClusterRepository
from renku_data_services.errors import errors
from renku_data_services.k8s import models as k8s_models
from renku_data_services.k8s.clients import K8sCachedClusterClient, K8sClusterClient
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER
from renku_data_services.k8s.db import K8sDbCache

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

    def sync_api(self) -> kr8s.Api:
        """Instantiate the sync Kr8s Api object based on the configuration."""
        return kr8s.api(
            kubeconfig=self._kubeconfig,
            namespace=self._ns,
            context=self._current_context_name,
        )

    def _async_api(self) -> Awaitable[kr8s.asyncio.Api]:
        """Create an async api client from sync code.

        Kr8s cannot return an AsyncAPI instance from sync code, and we can't easily make all our config code async,
        so this method is a direct copy of the kr8s sync client code, just that it returns an async client.
        """
        return kr8s.asyncio.api(
            url=self._url,
            kubeconfig=self._kubeconfig,
            serviceaccount=self._sa,
            namespace=self._ns,
            context=self._current_context_name,
            _asyncio=True,  # This is the only line that is different from kr8s code
        )

    def api(self) -> Awaitable[kr8s.asyncio.Api]:
        """Instantiate the async Kr8s Api object based on the configuration."""
        return self._async_api()


class KubeConfigEnv(KubeConfig):
    """Get a kube config from the environment."""

    def __init__(self) -> None:
        super().__init__(ns=os.environ.get("K8S_NAMESPACE", "default"))


async def from_kubeconfig_file(kubeconfig_path: str) -> KubeConfig:
    """Generate a config from a kubeconfig file."""

    async with aiofiles.open(kubeconfig_path) as stream:
        kubeconfig_contents = await stream.read()

    conf = yaml.safe_load(kubeconfig_contents)
    if not isinstance(conf, dict):
        raise errors.ConfigurationError(message=f"The kubeconfig {kubeconfig_path} is empty or has a bad format.")

    current_context_name = conf.get("current-context", None)
    ns = None
    if current_context_name is not None:
        for context in conf.get("contexts", []):
            if not isinstance(context, dict):
                continue
            name = context.get("name", None)
            inner = context.get("context", None)
            if inner is not None and name == current_context_name:
                ns = inner.get("namespace", None)
                break

    return KubeConfig(kubeconfig_path, current_context_name=current_context_name, ns=ns)


async def get_clusters(
    kube_conf_root_dir: str,
    default_kubeconfig: KubeConfig,
    cluster_repo: ClusterRepository,
    cache: K8sDbCache | None = None,
    kinds_to_cache: list[k8s_models.GVK] | None = None,
) -> AsyncIterable[K8sClusterClient]:
    """Get all clusters accessible to the application."""
    default_api = await default_kubeconfig.api()
    cluster_connection = k8s_models.ClusterConnection(
        id=DEFAULT_K8S_CLUSTER, namespace=default_api.namespace, api=default_api
    )
    if cache is None or kinds_to_cache is None:
        yield K8sClusterClient(cluster_connection)
    else:
        yield K8sCachedClusterClient(cluster_connection, cache, kinds_to_cache)

    if not os.path.exists(kube_conf_root_dir):
        logger.warning(f"Cannot open directory '{kube_conf_root_dir}', ignoring kube configs...")
        return

    async for cluster_db in cluster_repo.select_all():
        filename = cluster_db.config_name
        logger.info(f"Trying to load Kubernetes config: '{kube_conf_root_dir}/{filename}'")
        try:
            logger.info(f"Reading: '{kube_conf_root_dir}/{filename}'")
            kube_config = await from_kubeconfig_file(f"{kube_conf_root_dir}/{filename}")
            logger.info(f"Creating API for '{kube_conf_root_dir}/{filename}'")
            k8s_api = await kube_config.api()
            logger.info(f"Creating cluster connection for '{kube_conf_root_dir}/{filename}'")
            cluster_connection = k8s_models.ClusterConnection(
                id=cluster_db.id,
                namespace=k8s_api.namespace,
                api=await k8s_api,
            )
            if cache is None or kinds_to_cache is None:
                logger.info(f"Creating k8s client for '{kube_conf_root_dir}/{filename}'")
                cluster = K8sClusterClient(cluster_connection)
            else:
                logger.info(f"Creating cached k8s client for '{kube_conf_root_dir}/{filename}'")
                cluster = K8sCachedClusterClient(cluster_connection, cache, kinds_to_cache)

            logger.info(f"Successfully loaded Kubernetes config: '{kube_conf_root_dir}/{filename}'")
            yield cluster
        except Exception as e:
            logger.warning(f"Failed while loading '{kube_conf_root_dir}/{filename}', ignoring kube config. Error: {e}")
