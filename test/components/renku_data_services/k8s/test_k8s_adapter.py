from dataclasses import asdict

from box import Box
from hypothesis import given
from kr8s.asyncio.objects import StatefulSet
from kubernetes import client
from kubernetes.client import (
    V1Container,
    V1EnvVar,
    V1EnvVarSource,
    V1LabelSelector,
    V1PodSpec,
    V1PodTemplateSpec,
    V1StatefulSet,
    V1StatefulSetSpec,
)

from renku_data_services.crc import models
from renku_data_services.k8s.clients import DummyCoreClient, DummySchedulingClient
from renku_data_services.k8s.db import QuotaRepository
from renku_data_services.notebooks.api.classes.auth import RenkuTokens
from renku_data_services.notebooks.api.classes.k8s_client import NotebookK8sClient
from renku_data_services.notebooks.util.kubernetes_ import find_env_var
from test.components.renku_data_services.crc_models.hypothesis import quota_strat


def test_dummy_core_client() -> None:
    core_client = DummyCoreClient({}, {})
    quotas = core_client.list_resource_quota("default", "")
    assert len(quotas) == 0
    assert len(core_client.quotas) == 0
    quota_name = "test"
    quota = client.V1ResourceQuota(
        metadata={"name": quota_name}, spec=client.V1ResourceQuotaSpec(hard={"requests.cpu": 1})
    )
    core_client.create_resource_quota("default", quota)
    quotas = core_client.list_resource_quota("default", "")
    assert len(quotas) == 1
    assert len(core_client.quotas) == 1
    core_client.delete_resource_quota(quota_name, "default")
    quotas = core_client.list_resource_quota("default", "")
    assert len(quotas) == 0
    assert len(core_client.quotas) == 0


def test_dummy_scheduling_client() -> None:
    scheduling_client = DummySchedulingClient({})
    assert len(scheduling_client.pcs) == 0
    pc_name = "test"
    pc = client.V1PriorityClass(global_default=False, value=100, metadata=client.V1ObjectMeta(name=pc_name))
    scheduling_client.create_priority_class(pc)
    assert len(scheduling_client.pcs) == 1
    scheduling_client.delete_priority_class(pc_name, body=client.V1DeleteOptions())
    assert len(scheduling_client.pcs) == 0


@given(quota=quota_strat)
def test_get_insert_quota(quota: models.Quota) -> None:
    core_client = DummyCoreClient({}, {})
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
def test_delete_quota(quota: models.Quota) -> None:
    core_client = DummyCoreClient({}, {})
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
def test_update_quota(old_quota: models.Quota, new_quota: models.Quota) -> None:
    try:
        core_client = DummyCoreClient({}, {})
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


def test_find_env_var() -> None:
    env = [Box(name="key1", value="val1"), Box(name="key2", value="val2")]
    assert find_env_var(env, "key1") == (0, env[0])
    assert find_env_var(env, "key2") == (1, env[1])
    assert find_env_var(env, "missing") is None


def test_patch_statefulset_tokens() -> None:
    git_clone_access_env = "GIT_CLONE_USER__RENKU_TOKEN"
    git_proxy_access_env = "GIT_PROXY_RENKU_ACCESS_TOKEN"
    git_proxy_refresh_env = "GIT_PROXY_RENKU_REFRESH_TOKEN"
    secrets_access_env = "RENKU_ACCESS_TOKEN"
    git_clone = V1Container(
        name="git-clone",
        env=[
            V1EnvVar(name="test", value="value"),
            V1EnvVar(git_clone_access_env, "old_value"),
            V1EnvVar(name="test-from-source", value_from=V1EnvVarSource()),
        ],
    )
    git_proxy = V1Container(
        name="git-proxy",
        env=[
            V1EnvVar(name="test", value="value"),
            V1EnvVar(name="test-from-source", value_from=V1EnvVarSource()),
            V1EnvVar(git_proxy_refresh_env, "old_value"),
            V1EnvVar(git_proxy_access_env, "old_value"),
        ],
    )
    secrets = V1Container(
        name="init-user-secrets",
        env=[
            V1EnvVar(secrets_access_env, "old_value"),
            V1EnvVar(name="test", value="value"),
            V1EnvVar(name="test-from-source", value_from=V1EnvVarSource()),
        ],
    )
    random1 = V1Container(name="random1")
    random2 = V1Container(
        name="random2",
        env=[
            V1EnvVar(name="test", value="value"),
            V1EnvVar(name="test-from-source", value_from=V1EnvVarSource()),
        ],
    )

    new_renku_tokens = RenkuTokens(access_token="new_renku_access_token", refresh_token="new_renku_refresh_token")

    sts = V1StatefulSet(
        spec=V1StatefulSetSpec(
            service_name="test",
            selector=V1LabelSelector(),
            template=V1PodTemplateSpec(
                spec=V1PodSpec(
                    containers=[git_proxy, random1, random2], init_containers=[git_clone, random1, secrets, random2]
                )
            ),
        )
    )
    sanitized_sts = client.ApiClient().sanitize_for_serialization(sts)
    patches = NotebookK8sClient._get_statefulset_token_patches(StatefulSet(sanitized_sts), new_renku_tokens)

    # Order of patches should be git proxy access, git proxy refresh, git clone, secrets
    assert len(patches) == 4
    # Git proxy access token
    assert patches[0]["path"] == "/spec/template/spec/containers/0/env/3/value"
    assert patches[0]["value"] == new_renku_tokens.access_token
    # Git proxy refresh token
    assert patches[1]["path"] == "/spec/template/spec/containers/0/env/2/value"
    assert patches[1]["value"] == new_renku_tokens.refresh_token
    # Git clone
    assert patches[2]["path"] == "/spec/template/spec/initContainers/0/env/1/value"
    assert patches[2]["value"] == new_renku_tokens.access_token
    # Secrets init
    assert patches[3]["path"] == "/spec/template/spec/initContainers/2/env/0/value"
    assert patches[3]["value"] == new_renku_tokens.access_token
