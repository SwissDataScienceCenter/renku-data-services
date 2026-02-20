"""Kubernetes PriorityClass wrappers."""

from __future__ import annotations

from typing import Protocol, Self

from box import Box

from renku_data_services.k8s.constants import ClusterId
from renku_data_services.k8s.core import DeletePropagationPolicy, K8sClient
from renku_data_services.k8s.models import GVK, K8sObject, K8sObjectMeta


class K8sPriorityClass(K8sObject):
    """Represents a PriorityClass in k8s."""

    def __init__(
        self,
        name: str,
        cluster: ClusterId,
        manifest: Box,
    ) -> None:
        super().__init__(
            name=name,
            namespace=None,
            cluster=cluster,
            gvk=GVK(kind="PriorityClass", version="v1", group="scheduling.k8s.io"),
            manifest=manifest,
        )

    @classmethod
    def new(
        cls,
        name: str,
        cluster: ClusterId,
        global_default: bool,
        value: int,
        preemption_policy: str,
        description: str,
        labels: dict[str, str],
    ) -> Self:
        """Instantiate a K8sPriorityClass."""
        return cls(
            name=name,
            cluster=cluster,
            manifest=Box(
                {
                    "metadata": {
                        "name": name,
                        "labels": labels,
                    },
                    "description": description,
                    "globalDefault": global_default,
                    "preemptionPolicy": preemption_policy,
                    "value": value,
                }
            ),
        )

    @classmethod
    def meta(cls, name: str, cluster_id: ClusterId) -> K8sObjectMeta:
        """Return a K8sObjectMeta describing the named resource quota."""
        return K8sObjectMeta(
            name=name,
            namespace=None,
            cluster=cluster_id,
            gvk=GVK(kind="PriorityClass", version="v1", group="scheduling.k8s.io"),
        )

    @classmethod
    def from_k8s_object(cls, k8s_object: K8sObject) -> Self:
        """Convert a k8s object to a K8sPriorityClass object."""
        assert k8s_object.namespace is None

        return cls(
            name=k8s_object.name,
            cluster=k8s_object.cluster,
            manifest=k8s_object.manifest,
        )


class PriorityClassClient(Protocol):
    """Methods to manipulate kubernetes Priority Class resources."""

    async def create_priority_class(self, priority_class: K8sPriorityClass) -> K8sPriorityClass:
        """Create a priority class."""
        ...

    async def read_priority_class(self, meta: K8sObjectMeta) -> K8sPriorityClass | None:
        """Retrieve a priority class."""
        ...

    async def delete_priority_class(
        self,
        meta: K8sObjectMeta,
        propagation_policy: DeletePropagationPolicy = DeletePropagationPolicy.foreground,
    ) -> None:
        """Delete a priority class."""
        ...


class K8sPriorityClassClient(PriorityClassClient):
    """Real k8s scheduling API client that exposes the required functions."""

    def __init__(self, client: K8sClient) -> None:
        self.__client = client

    async def create_priority_class(self, priority_class: K8sPriorityClass) -> K8sPriorityClass:
        """Create a priority class."""
        return K8sPriorityClass.from_k8s_object(await self.__client.create(priority_class, refresh=True))

    async def delete_priority_class(
        self,
        meta: K8sObjectMeta,
        propagation_policy: DeletePropagationPolicy = DeletePropagationPolicy.foreground,
    ) -> None:
        """Delete a priority class."""
        await self.__client.delete(meta, propagation_policy)

    async def read_priority_class(self, meta: K8sObjectMeta) -> K8sPriorityClass | None:
        """Get a priority class."""
        output = await self.__client.get(meta)
        if output is None:
            return None
        return K8sPriorityClass.from_k8s_object(output)


class DummyPriorityClassClient(PriorityClassClient):
    """Dummy k8s scheduling API client that does not require a k8s cluster.

    Not suitable for production - to be used only for testing and development.
    """

    async def create_priority_class(self, priority_class: K8sPriorityClass) -> K8sPriorityClass:
        """Create a priority class."""
        raise NotImplementedError()

    async def read_priority_class(self, meta: K8sObjectMeta) -> K8sPriorityClass | None:
        """Get a priority class."""
        raise NotImplementedError()

    async def delete_priority_class(
        self,
        meta: K8sObjectMeta,
        propagation_policy: DeletePropagationPolicy = DeletePropagationPolicy.foreground,
    ) -> None:
        """Delete a priority class."""
        raise NotImplementedError()
