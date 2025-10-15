"""Different implementations of k8s clients."""

from __future__ import annotations

import contextlib
import multiprocessing.synchronize
from collections.abc import AsyncIterable
from copy import deepcopy
from multiprocessing import Lock
from multiprocessing.synchronize import Lock as LockType
from typing import Any
from uuid import uuid4

import kr8s
from kubernetes import client, config
from kubernetes.config.config_exception import ConfigException
from kubernetes.config.incluster_config import SERVICE_CERT_FILENAME, SERVICE_TOKEN_FILENAME, InClusterConfigLoader

from renku_data_services.errors import errors
from renku_data_services.k8s.client_interfaces import K8sClient, PriorityClassClient, ResourceQuotaClient, SecretClient
from renku_data_services.k8s.constants import ClusterId
from renku_data_services.k8s.db import K8sDbCache
from renku_data_services.k8s.models import (
    GVK,
    APIObjectInCluster,
    ClusterConnection,
    K8sObject,
    K8sObjectFilter,
    K8sObjectMeta,
    K8sSecret,
)


class K8sCoreClient(ResourceQuotaClient):
    """Real k8s core API client that exposes the required functions."""

    def __init__(self) -> None:
        try:
            InClusterConfigLoader(
                token_filename=SERVICE_TOKEN_FILENAME,
                cert_filename=SERVICE_CERT_FILENAME,
            ).load_and_set()
        except ConfigException:
            config.load_config()
        self.client = client.CoreV1Api()

    def read_resource_quota(self, name: str, namespace: str) -> client.V1ResourceQuota:
        """Get a resource quota."""
        return self.client.read_namespaced_resource_quota(name, namespace)

    def list_resource_quota(self, namespace: str, label_selector: str) -> list[client.V1ResourceQuota]:
        """List resource quotas."""
        return list(self.client.list_namespaced_resource_quota(namespace, label_selector=label_selector).items())

    def create_resource_quota(self, namespace: str, body: client.V1ResourceQuota) -> None:
        """Create a resource quota."""
        self.client.create_namespaced_resource_quota(namespace, body)

    def delete_resource_quota(self, name: str, namespace: str) -> None:
        """Delete a resource quota."""
        try:
            self.client.delete_namespaced_resource_quota(name, namespace)
        except client.ApiException as e:
            if e.status == 404:
                # If the thing we are trying to delete is not there, we have the desired state so we can just go on.
                return None
            raise

    def patch_resource_quota(self, name: str, namespace: str, body: client.V1ResourceQuota) -> None:
        """Update a resource quota."""
        self.client.patch_namespaced_resource_quota(name, namespace, body)


class K8sSecretClient(SecretClient):
    """A wrapper around a kr8s k8s client, acts on Secrets."""

    def __init__(self, client: K8sClient) -> None:
        self.__client = client

    async def create_secret(self, secret: K8sSecret) -> K8sSecret:
        """Create a secret."""

        return K8sSecret.from_k8s_object(await self.__client.create(secret, False))

    async def patch_secret(self, secret: K8sObjectMeta, patch: dict[str, Any] | list[dict[str, Any]]) -> K8sSecret:
        """Patch a secret."""

        return K8sSecret.from_k8s_object(await self.__client.patch(secret, patch))

    async def delete_secret(self, secret: K8sObjectMeta) -> None:
        """Delete a secret."""

        await self.__client.delete(secret)


class K8sSchedulingClient(PriorityClassClient):
    """Real k8s scheduling API client that exposes the required functions."""

    def __init__(self) -> None:
        try:
            InClusterConfigLoader(
                token_filename=SERVICE_TOKEN_FILENAME,
                cert_filename=SERVICE_CERT_FILENAME,
            ).load_and_set()
        except ConfigException:
            config.load_config()
        self.client = client.SchedulingV1Api()

    def create_priority_class(self, body: client.V1PriorityClass) -> client.V1PriorityClass:
        """Create a priority class."""
        return self.client.create_priority_class(body)

    def delete_priority_class(self, name: str, body: client.V1DeleteOptions) -> None:
        """Delete a priority class."""
        try:
            self.client.delete_priority_class(name, body=body)
        except client.ApiException as e:
            if e.status != 404:
                # NOTE: The priorityclass is an owner of the resource quota so when the priority class is deleted the
                # resource quota is also deleted. Also, we don't care if the thing we are trying to delete is not there
                # we have the desired state so we can just go on.
                raise

    def read_priority_class(self, name: str) -> client.V1PriorityClass | None:
        """Get a priority class."""
        pc = None
        with contextlib.suppress(client.ApiException):
            pc = self.client.read_priority_class(name)
        return pc


class DummyCoreClient(ResourceQuotaClient, SecretClient):
    """Dummy k8s core API client that does not require a k8s cluster.

    Not suitable for production - to be used only for testing and development.
    """

    def __init__(self, quotas: dict[str, client.V1ResourceQuota], secrets: dict[str, K8sSecret]) -> None:
        self.quotas = quotas
        self.secrets = secrets
        self.__lock: LockType | None = None

    @property
    def _lock(self) -> multiprocessing.synchronize.Lock:
        # NOTE: If this is a regular attribute and initialized when the class in initialized
        # then Sanic fails to start properly because it clashes with the multiprocessing Lock
        # used here. This way Sanic starts without a problem because the Lock is initialized
        # after Sanic has started.
        if not self.__lock:
            self.__lock = Lock()
        return self.__lock

    def read_resource_quota(self, name: str, namespace: str) -> client.V1ResourceQuota:
        """Get a resource quota."""
        with self._lock:
            quota = self.quotas.get(name)
            if quota is None:
                raise client.ApiException(status=404)
            return quota

    def list_resource_quota(self, namespace: str, label_selector: str) -> list[client.V1ResourceQuota]:
        """List resource quotas."""
        with self._lock:
            return list(self.quotas.values())

    def create_resource_quota(self, namespace: str, body: client.V1ResourceQuota) -> None:
        """Create a resource quota."""
        with self._lock:
            if isinstance(body.metadata, dict):
                body.metadata = client.V1ObjectMeta(**body.metadata)
            body.metadata.uid = uuid4()
            body.api_version = "v1"
            body.kind = "ResourceQuota"
            self.quotas[body.metadata.name] = body

    def delete_resource_quota(self, name: str, namespace: str) -> None:
        """Delete a resource quota."""
        with self._lock:
            self.quotas.pop(name, None)

    def patch_resource_quota(self, name: str, namespace: str, body: client.V1ResourceQuota) -> None:
        """Update a resource quota."""
        with self._lock:
            old_quota = self.quotas.get(name)
            if old_quota is None:
                raise client.ApiException(status=404)
            new_quota = deepcopy(old_quota)
            if isinstance(body, client.V1ResourceQuota):
                new_quota.spec = body.spec
            if isinstance(body, dict):
                new_quota.spec = client.V1ResourceQuota(**body).spec
            self.quotas[name] = new_quota

    async def create_secret(self, secret: K8sSecret) -> K8sSecret:
        """Create a secret."""
        with self._lock:
            secret.manifest.metadata.uid = uuid4()
            self.secrets[secret.name] = secret
            return secret

    async def patch_secret(self, secret: K8sObjectMeta, patch: dict[str, Any] | list[dict[str, Any]]) -> K8sSecret:
        """Patch a secret."""
        # NOTE: This is only needed if the create_namespaced_secret can raise a conflict 409 status code
        # error when it tries to create a secret that already exists. But the dummy client never raises
        # this so we don't need to implement it (for now).
        raise NotImplementedError()

    async def delete_secret(self, secret: K8sObjectMeta) -> None:
        """Delete a secret."""
        raise NotImplementedError()


class DummySchedulingClient(PriorityClassClient):
    """Dummy k8s scheduling API client that does not require a k8s cluster.

    Not suitable for production - to be used only for testing and development.
    """

    def __init__(self, pcs: dict[str, client.V1PriorityClass]) -> None:
        self.pcs = pcs
        self.__lock: LockType | None = None

    @property
    def _lock(self) -> multiprocessing.synchronize.Lock:
        # NOTE: If this is a regular attribute and initialized when the class in initialized
        # then Sanic fails to start properly because it clashes with the multiprocessing Lock
        # used here. This way Sanic starts without a problem because the Lock is initialized
        # after Sanic has started.
        if not self.__lock:
            self.__lock = Lock()
        return self.__lock

    def create_priority_class(self, body: client.V1PriorityClass) -> client.V1PriorityClass:
        """Create a priority class."""
        with self._lock:
            if isinstance(body.metadata, dict):
                body.metadata = client.V1ObjectMeta(**body.metadata)
            body.metadata.uid = uuid4()
            body.api_version = "v1"
            body.kind = "PriorityClass"
            self.pcs[body.metadata.name] = body
            return body

    def read_priority_class(self, name: str) -> client.V1PriorityClass | None:
        """Get a priority class."""
        with self._lock:
            return self.pcs.get(name, None)

    def delete_priority_class(self, name: str, body: client.V1DeleteOptions) -> None:
        """Delete a priority class."""
        with self._lock:
            self.pcs.pop(name, None)


class K8sClusterClient(K8sClient):
    """A wrapper around a kr8s k8s client, acts on all resources of a cluster."""

    def __init__(self, cluster: ClusterConnection) -> None:
        self.__cluster = cluster
        assert self.__cluster.api is not None

    def __lt__(self, other: K8sClusterClient) -> bool:
        """Allows for sorting."""
        return self.__cluster.id < other.__cluster.id and self.__cluster.namespace < other.__cluster.namespace

    def get_cluster(self) -> ClusterConnection:
        """Return a cluster object."""
        return self.__cluster

    async def __list(self, _filter: K8sObjectFilter) -> AsyncIterable[APIObjectInCluster]:
        if _filter.cluster is not None and _filter.cluster != self.__cluster.id:
            return

        names = [_filter.name] if _filter.name is not None else []

        try:
            res = self.__cluster.api.async_get(
                _filter.gvk.kr8s_kind,
                *names,
                label_selector=_filter.label_selector,
                namespace=_filter.namespace,
            )

            async for r in res:
                yield APIObjectInCluster(r, self.__cluster.id)

        except (kr8s.ServerError, kr8s.APITimeoutError, ValueError) as _e:
            # ValueError is generated when the kind does not exist on the cluster
            return

    async def __get_api_object(self, meta: K8sObjectFilter) -> APIObjectInCluster | None:
        return await anext(aiter(self.__list(meta)), None)

    async def create(self, obj: K8sObject, refresh: bool) -> K8sObject:
        """Create the k8s object."""

        api_obj = obj.to_api_object(self.__cluster.api)
        await api_obj.create()

        # In some cases the service account does not have read rights, in which case we cannot call get(), and refresh()
        if refresh:
            # if refresh isn't called, status and timestamp will be blank
            await api_obj.refresh()

        return obj.with_manifest(api_obj.to_dict())

    async def patch(self, meta: K8sObjectMeta, patch: dict[str, Any] | list[dict[str, Any]]) -> K8sObject:
        """Patch a k8s object.

        If the patch is a list we assume that we have a rfc6902 json patch like
        `[{ "op": "add", "path": "/a/b/c", "value": [ "foo", "bar" ] }]`.
        If the patch is a dictionary then it is considered to be a rfc7386 json merge patch.
        """
        obj = await self.__get_api_object(meta.to_filter())
        if obj is None:
            raise errors.MissingResourceError(message=f"The k8s resource with metadata {meta} cannot be found.")
        patch_type = "json" if isinstance(patch, list) else None
        await obj.obj.patch(patch, type=patch_type)
        await obj.obj.refresh()

        return meta.with_manifest(obj.obj.to_dict())

    async def delete(self, meta: K8sObjectMeta) -> None:
        """Delete a k8s object."""
        obj = await self.__get_api_object(meta.to_filter())
        if obj is None:
            return
        with contextlib.suppress(kr8s.NotFoundError):
            await obj.obj.delete(propagation_policy="Foreground")

    async def get(self, meta: K8sObjectMeta) -> K8sObject | None:
        """Get a specific k8s object, None is returned if the object does not exist."""
        obj = await self.__get_api_object(meta.to_filter())
        if obj is None:
            return None
        return meta.with_manifest(obj.obj.to_dict())

    async def list(self, _filter: K8sObjectFilter) -> AsyncIterable[K8sObject]:
        """List all k8s objects."""
        async for r in self.__list(_filter):
            yield r.to_k8s_object()


class K8sCachedClusterClient(K8sClusterClient):
    """A wrapper around a kr8s k8s client.

    Provides access to a cache for listing and reading resources but fallback to the cluster for other operations.
    """

    def __init__(self, cluster: ClusterConnection, cache: K8sDbCache, kinds_to_cache: list[GVK]) -> None:
        super().__init__(cluster)
        self.__cache = cache
        self.__kinds_to_cache = set(kinds_to_cache)

    async def create(self, obj: K8sObject, refresh: bool) -> K8sObject:
        """Create the k8s object."""
        if obj.gvk in self.__kinds_to_cache:
            await self.__cache.upsert(obj)
        try:
            obj = await super().create(obj, refresh)
        except:
            # if there was an error creating the k8s object, we delete it from the db again to not have ghost entries
            if obj.gvk in self.__kinds_to_cache:
                await self.__cache.delete(obj)
            raise
        return obj

    async def patch(self, meta: K8sObjectMeta, patch: dict[str, Any] | list[dict[str, Any]]) -> K8sObject:
        """Patch a k8s object."""
        obj = await super().patch(meta, patch)
        if meta.gvk in self.__kinds_to_cache:
            await self.__cache.upsert(obj)
        return obj

    async def delete(self, meta: K8sObjectMeta) -> None:
        """Delete a k8s object."""
        await super().delete(meta)
        # NOTE: We use foreground deletion in the k8s client.
        # This means that the parent resource is usually not deleted immediately and will
        # wait for its children to be deleted before it is deleted.
        # To avoid premature purging of resources from the cache we do not delete the resource here
        # from the cache, rather we expect that the cache will sync itself properly and quickly purge
        # stale resources.

    async def get(self, meta: K8sObjectMeta) -> K8sObject | None:
        """Get a specific k8s object, None is returned if the object does not exist."""
        if meta.gvk in self.__kinds_to_cache:
            res = await self.__cache.get(meta)
        else:
            res = await super().get(meta)

        return res

    async def list(self, _filter: K8sObjectFilter) -> AsyncIterable[K8sObject]:
        """List all k8s objects."""

        # Don't even go to the DB or Kubernetes if the cluster id is set and does not match our cluster.
        if _filter.cluster is not None and _filter.cluster != self.get_cluster().id:
            return

        filter2 = deepcopy(_filter)
        if filter2.cluster is None:
            filter2.cluster = self.get_cluster().id

        results = self.__cache.list(filter2) if _filter.gvk in self.__kinds_to_cache else super().list(filter2)
        async for res in results:
            yield res


class K8sClusterClientsPool(K8sClient):
    """A wrapper around a pool of kr8s k8s clients."""

    def __init__(self, clusters: AsyncIterable[K8sClusterClient]) -> None:
        self.__clusters = clusters
        self.__clients: dict[ClusterId, K8sClusterClient] = {}

    async def __init_clients_if_needed(self) -> None:
        if len(self.__clients) > 0:
            return
        async for cluster in self.__clusters:
            self.__clients[cluster.get_cluster().id] = cluster

    async def __get_client_or_die(self, cluster_id: ClusterId) -> K8sClusterClient:
        await self.__init_clients_if_needed()
        cluster_client = self.__clients.get(cluster_id)

        if cluster_client is None:
            raise errors.MissingResourceError(
                message=f"Could not find cluster with id {cluster_id} in the list of clusters."
            )
        return cluster_client

    async def cluster_by_id(self, cluster_id: ClusterId) -> ClusterConnection:
        """Return a cluster by its id."""
        client = await self.__get_client_or_die(cluster_id)
        return client.get_cluster()

    async def create(self, obj: K8sObject, refresh: bool = True) -> K8sObject:
        """Create the k8s object."""
        client = await self.__get_client_or_die(obj.cluster)
        return await client.create(obj, refresh)

    async def patch(self, meta: K8sObjectMeta, patch: dict[str, Any] | list[dict[str, Any]]) -> K8sObject:
        """Patch a k8s object."""
        client = await self.__get_client_or_die(meta.cluster)
        return await client.patch(meta, patch)

    async def delete(self, meta: K8sObjectMeta) -> None:
        """Delete a k8s object."""
        client = await self.__get_client_or_die(meta.cluster)
        await client.delete(meta)

    async def get(self, meta: K8sObjectMeta) -> K8sObject | None:
        """Get a specific k8s object, None is returned if the object does not exist."""
        client = await self.__get_client_or_die(meta.cluster)
        return await client.get(meta)

    async def list(self, _filter: K8sObjectFilter) -> AsyncIterable[K8sObject]:
        """List all k8s objects."""
        await self.__init_clients_if_needed()
        cluster_clients = sorted(list(self.__clients.values()))
        for c in cluster_clients:
            async for r in c.list(_filter):
                yield r
