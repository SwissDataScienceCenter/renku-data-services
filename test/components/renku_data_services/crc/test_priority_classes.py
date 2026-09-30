"""Tests for the quota and preemptible priority classes."""

from typing import Any

from box import Box

from renku_data_services.crc import models
from renku_data_services.crc.db import PREEMPTIBLE_PRIORITY_VALUE, SESSION_PRIORITY_VALUE, QuotaRepository
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER, ClusterId
from renku_data_services.k8s.models import DeletePropagationPolicy, K8sObjectMeta, K8sPriorityClass, K8sResourceQuota
from renku_data_services.notebooks.core_sessions import priority_class_from_resource_class


class FakePriorityClassClient:
    def __init__(self) -> None:
        self.classes: dict[str, K8sPriorityClass] = {}
        self.deleted: list[str] = []

    async def create_priority_class(self, priority_class: K8sPriorityClass) -> K8sPriorityClass:
        self.classes[priority_class.name] = priority_class
        return priority_class

    async def read_priority_class(self, meta: K8sObjectMeta) -> K8sPriorityClass | None:
        return self.classes.get(meta.name)

    async def delete_priority_class(
        self,
        meta: K8sObjectMeta,
        propagation_policy: DeletePropagationPolicy = DeletePropagationPolicy.foreground,
    ) -> None:
        self.deleted.append(meta.name)
        self.classes.pop(meta.name, None)


class FakeResourceQuotaClient:
    def __init__(self) -> None:
        self.quotas: dict[str, dict[str, Any]] = {}

    def _obj(self, name: str, cluster_id: ClusterId) -> K8sResourceQuota:
        return K8sResourceQuota(name=name, namespace="default", cluster=cluster_id, manifest=Box(self.quotas[name]))

    async def read_resource_quota(self, name: str, cluster_id: ClusterId) -> K8sResourceQuota:
        return self._obj(name, cluster_id)

    async def create_resource_quota(self, quota: dict[str, Any], cluster_id: ClusterId) -> K8sResourceQuota:
        name = quota["metadata"]["name"]
        self.quotas[name] = quota
        return self._obj(name, cluster_id)

    async def delete_resource_quota(self, name: str, cluster_id: ClusterId) -> None:
        self.quotas.pop(name, None)

    async def patch_resource_quota(self, name: str, patch: dict[str, Any], cluster_id: ClusterId) -> K8sResourceQuota:
        self.quotas[name]["spec"].update(patch["spec"])
        return self._obj(name, cluster_id)


def _repo() -> tuple[QuotaRepository, FakeResourceQuotaClient, FakePriorityClassClient]:
    rq_client = FakeResourceQuotaClient()
    pc_client = FakePriorityClassClient()
    return QuotaRepository(rq_client, pc_client), rq_client, pc_client  # type: ignore[arg-type]


def _resource_class(quota: str | None, preemptible: bool) -> models.ResourceClass:
    return models.ResourceClass(
        id=1, name="rc", cpu=1, memory=1, max_storage=1, gpu=0, quota=quota, preemptible=preemptible
    )


async def test_create_quota_makes_only_the_quota_priority_class() -> None:
    repo, rq_client, pc_client = _repo()

    quota = await repo.create_quota(models.UnsavedQuota(cpu=1, memory=1, gpu=0), DEFAULT_K8S_CLUSTER)

    assert list(pc_client.classes) == [quota.id]
    pc = pc_client.classes[quota.id].manifest
    assert pc.value == SESSION_PRIORITY_VALUE
    assert pc.preemptionPolicy == "PreemptLowerPriority"
    assert rq_client.quotas[quota.id]["spec"]["scopeSelector"] == models.quota_scope_selector(quota.id)
    assert models.quota_scope_selector(quota.id)["matchExpressions"][0]["values"] == [
        quota.id,
        f"{quota.id}-preemptible",
    ]


async def test_ensure_preemptible_priority_class() -> None:
    repo, _, pc_client = _repo()

    await repo.ensure_preemptible_priority_class("q1", DEFAULT_K8S_CLUSTER)
    await repo.ensure_preemptible_priority_class("q1", DEFAULT_K8S_CLUSTER)

    pc = pc_client.classes["q1-preemptible"].manifest
    assert pc.value == PREEMPTIBLE_PRIORITY_VALUE
    assert pc.preemptionPolicy == "Never"
    assert pc_client.deleted == []


async def test_migrate_quota_recreates_old_priority_class_and_patches_scope() -> None:
    repo, rq_client, pc_client = _repo()
    old_pc = K8sPriorityClass.new(
        name="q1",
        cluster=DEFAULT_K8S_CLUSTER,
        global_default=False,
        value=SESSION_PRIORITY_VALUE,
        preemption_policy="Never",
        description="old",
        labels={},
    )
    await pc_client.create_priority_class(old_pc)
    rq_client.quotas["q1"] = {
        "metadata": {"name": "q1"},
        "spec": {
            "scopeSelector": {"matchExpressions": [{"operator": "In", "scopeName": "PriorityClass", "values": ["q1"]}]}
        },
    }

    await repo.migrate_quota("q1", DEFAULT_K8S_CLUSTER)

    assert pc_client.deleted == ["q1"]
    assert list(pc_client.classes) == ["q1"]
    assert pc_client.classes["q1"].manifest.preemptionPolicy == "PreemptLowerPriority"
    assert rq_client.quotas["q1"]["spec"]["scopeSelector"] == models.quota_scope_selector("q1")


async def test_delete_quota_deletes_both_priority_classes() -> None:
    repo, _, pc_client = _repo()
    quota = await repo.create_quota(models.UnsavedQuota(cpu=1, memory=1, gpu=0), DEFAULT_K8S_CLUSTER)
    await repo.ensure_preemptible_priority_class(quota.id, DEFAULT_K8S_CLUSTER)

    await repo.delete_quota(quota.id, DEFAULT_K8S_CLUSTER)

    assert pc_client.classes == {}


def test_priority_class_from_resource_class() -> None:
    assert priority_class_from_resource_class(_resource_class(None, False)) is None
    assert priority_class_from_resource_class(_resource_class(None, True)) is None
    assert priority_class_from_resource_class(_resource_class("q1", False)) == "q1"
    assert priority_class_from_resource_class(_resource_class("q1", True)) == "q1-preemptible"
