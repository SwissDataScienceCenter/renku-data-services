from dataclasses import asdict
from test.components.renku_data_services.crc_models.hypothesis import quota_strat

from hypothesis import given
from kubernetes import client

from renku_data_services.crc import models
from renku_data_services.k8s.clients import DummyCoreClient, DummySchedulingClient
from renku_data_services.k8s.quota import QuotaRepository


def test_dummy_core_client():
    core_client = DummyCoreClient({})
    quotas = core_client.list_namespaced_resource_quota("default")
    assert len(quotas.items) == 0
    assert len(core_client.quotas) == 0
    quota_name = "test"
    quota = client.V1ResourceQuota(
        metadata={"name": quota_name}, spec=client.V1ResourceQuotaSpec(hard={"requests.cpu": 1})
    )
    core_client.create_namespaced_resource_quota("default", quota)
    quotas = core_client.list_namespaced_resource_quota("default")
    assert len(quotas.items) == 1
    assert len(core_client.quotas) == 1
    core_client.delete_namespaced_resource_quota(quota_name, "default")
    quotas = core_client.list_namespaced_resource_quota("default")
    assert len(quotas.items) == 0
    assert len(core_client.quotas) == 0


def test_dummy_scheduling_client():
    scheduling_client = DummySchedulingClient({})
    assert len(scheduling_client.pcs) == 0
    pc_name = "test"
    pc = client.V1PriorityClass(global_default=False, value=100, metadata=client.V1ObjectMeta(name=pc_name))
    scheduling_client.create_priority_class(pc)
    assert len(scheduling_client.pcs) == 1
    scheduling_client.delete_priority_class(pc_name)
    assert len(scheduling_client.pcs) == 0


@given(quota=quota_strat)
def test_get_insert_quota(quota: models.Quota):
    core_client = DummyCoreClient({})
    scheduling_client = DummySchedulingClient({})
    quota_repo = QuotaRepository(core_client, scheduling_client)
    quotas = quota_repo.get_quotas()
    assert len(quotas) == 0
    assert len(scheduling_client.pcs) == 0
    quota_repo.create_quota(quota)
    quotas = quota_repo.get_quotas()
    assert len(quotas) == 1
    inserted_quota = quotas[0]
    assert len(scheduling_client.pcs) == 1
    assert scheduling_client.pcs[inserted_quota.id].metadata.name == inserted_quota.id
    specific_quota_list = quota_repo.get_quotas(quota.id)
    assert len(specific_quota_list) == 1
    specific_quota = specific_quota_list[0]
    assert specific_quota is not None
    assert specific_quota in quotas


@given(quota=quota_strat)
def test_delete_quota(quota: models.Quota):
    core_client = DummyCoreClient({})
    scheduling_client = DummySchedulingClient({})
    quota_repo = QuotaRepository(core_client, scheduling_client)
    quota_repo.create_quota(quota)
    quotas = quota_repo.get_quotas()
    assert len(quotas) == 1
    assert len(scheduling_client.pcs) == 1
    quota_repo.delete_quota(quotas[0].id)
    quotas = quota_repo.get_quotas()
    assert len(quotas) == 0
    assert len(scheduling_client.pcs) == 0


@given(old_quota=quota_strat, new_quota=quota_strat)
def test_update_quota(old_quota: models.Quota, new_quota: models.Quota):
    try:
        core_client = DummyCoreClient({})
        scheduling_client = DummySchedulingClient({})
        quota_repo = QuotaRepository(core_client, scheduling_client)
        old_quota = quota_repo.create_quota(old_quota)
        quotas = quota_repo.get_quotas()
        assert len(scheduling_client.pcs) == 1
        assert len(quotas) == 1
        new_quota = models.Quota.from_dict({**asdict(new_quota), "id": old_quota.id})
        quota_repo.update_quota(new_quota)
        quotas = quota_repo.get_quotas()
        assert len(quotas) == 1
        assert len(scheduling_client.pcs) == 1
        assert quotas[0] == new_quota
    finally:
        if old_quota is not None:
            quota_repo.delete_quota(old_quota.id)
