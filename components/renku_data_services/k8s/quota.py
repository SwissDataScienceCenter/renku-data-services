"""The adapter used to create/delete/update/get resource quotas and priority classes in k8s."""

from contextlib import suppress
from dataclasses import dataclass, field
from typing import Optional

from kubernetes import client
from kubernetes.utils.quantity import parse_quantity

from renku_data_services import errors
from renku_data_services.crc import models
from renku_data_services.k8s.client_interfaces import K8sCoreClientInterface, K8sSchedudlingClientInterface


@dataclass
class QuotaRepository:
    """Adapter for CRUD operations on resource quotas and priority classes in k8s."""

    core_client: K8sCoreClientInterface
    scheduling_client: K8sSchedudlingClientInterface
    namespace: str = "default"
    _label_name: str = field(init=False, default="app")
    _label_value: str = field(init=False, default="renku")

    def _quota_from_manifest(self, manifest: client.V1ResourceQuota) -> models.Quota:
        gpu = 0
        gpu_kind = models.GpuKind.NVIDIA
        for igpu_kind in models.GpuKind:
            key = f"requests.{igpu_kind}/gpu"
            if key in manifest.spec.hard:
                gpu = int(manifest.spec.hard.get(key))
                gpu_kind = igpu_kind
                break
        memory_raw = manifest.spec.hard.get("requests.memory")
        if memory_raw is None:
            raise errors.ValidationError(
                message="Kubernetes resource quota with missing hard.requests.memory is not supported"
            )
        cpu_raw = manifest.spec.hard.get("requests.cpu")
        if cpu_raw is None:
            raise errors.ValidationError(
                message="Kubernetes resource quota with missing hard.requests.cpu is not supported"
            )
        return models.Quota(
            cpu=float(parse_quantity(cpu_raw)),
            memory=round(parse_quantity(memory_raw) / 1_000_000_000),
            gpu=gpu,
            gpu_kind=gpu_kind,
            id=manifest.metadata.name,
        )

    def _quota_to_manifest(self, quota: models.Quota) -> client.V1ResourceQuota:
        if quota.id is None:
            raise errors.ValidationError(message="The id of a quota has to be set when it is created.")
        return client.V1ResourceQuota(
            metadata=client.V1ObjectMeta(labels={self._label_name: self._label_value}, name=quota.id),
            spec=client.V1ResourceQuotaSpec(
                hard={
                    "requests.cpu": quota.cpu,
                    "requests.memory": str(quota.memory * 1_000_000_000),
                    f"requests.{quota.gpu_kind}/gpu": quota.gpu,
                },
                scope_selector=client.V1ScopeSelector(
                    match_expressions=[{"operator": "In", "scopeName": "PriorityClass", "values": [quota.id]}]
                ),
            ),
        )

    def get_quota(self, name: str | None) -> Optional[models.Quota]:
        """Get a specific quota by name."""
        if not name:
            return None
        try:
            res_quota: client.V1ResourceQuota = self.core_client.read_namespaced_resource_quota(
                name=name, namespace=self.namespace
            )
        except client.ApiException as e:
            if e.status == 404:
                return None
            raise
        return self._quota_from_manifest(res_quota)

    def get_quotas(self, name: Optional[str] = None) -> list[models.Quota]:
        """Get a specific resource quota."""
        if name is not None:
            quota = self.get_quota(name)
            return [quota] if quota is not None else []
        quotas = self.core_client.list_namespaced_resource_quota(
            namespace=self.namespace, label_selector=f"{self._label_name}={self._label_value}"
        )
        return [self._quota_from_manifest(q) for q in quotas.items]

    def create_quota(self, quota: models.Quota) -> models.Quota:
        """Create a resource quota and priority class."""

        metadata = {"labels": {self._label_name: self._label_value}, "name": quota.id}
        quota_manifest = self._quota_to_manifest(quota)

        # LSA Check if we have a priority class with the given name, return it or create one otherwise.
        pc: client.V1PriorityClass | None = None
        with suppress(client.ApiException):
            pc = self.scheduling_client.get_priority_class(quota.id)
        if pc is None:
            pc = self.scheduling_client.create_priority_class(
                client.V1PriorityClass(
                    global_default=False,
                    value=100,
                    preemption_policy="Never",
                    description="Renku resource quota priority class",
                    metadata=client.V1ObjectMeta(**metadata),
                ),
            )

        # NOTE: The priority class is cluster-scoped and a namespace-scoped resource cannot be an owner
        # of a cluster-scoped resource. That is why the priority class is an owner of the quota.
        quota_manifest.owner_references = [
            client.V1OwnerReference(
                api_version=pc.api_version,
                block_owner_deletion=True,
                controller=False,
                kind=pc.kind,
                name=pc.metadata.name,
                uid=pc.metadata.uid,
            )
        ]
        self.core_client.create_namespaced_resource_quota(self.namespace, quota_manifest)
        return quota

    def delete_quota(self, name: str) -> None:
        """Delete a resource quota and priority class."""
        try:
            self.scheduling_client.delete_priority_class(
                name=name, body=client.V1DeleteOptions(propagation_policy="Foreground")
            )
            self.core_client.delete_namespaced_resource_quota(name=name, namespace=self.namespace)
        except client.ApiException as e:
            if e.status == 404:
                # NOTE: The priorityclass is an owner of the resource quota so when the priority class is deleted the
                # resource quota is also deleted. Also, we don't care if the thing we are trying to delete is not there
                # we have the desired state so we can just go on.
                return
            raise

    def update_quota(self, quota: models.Quota) -> models.Quota:
        """Update a specific resource quota."""

        quota_manifest = self._quota_to_manifest(quota)
        self.core_client.patch_namespaced_resource_quota(name=quota.id, namespace=self.namespace, body=quota_manifest)
        return quota
