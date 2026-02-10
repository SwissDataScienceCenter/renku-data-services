import asyncio
from dataclasses import asdict

import pytest
import pytest_asyncio
from box import Box
from hypothesis import given, settings
from kr8s.asyncio.objects import StatefulSet
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
from renku_data_services.k8s.clients import (
    K8sClusterClient,
    K8sResourceQuotaClient,
    K8sSchedulingClient,
)
from renku_data_services.k8s.config import from_kubeconfig_file
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER
from renku_data_services.k8s.db import QuotaRepository
from renku_data_services.k8s.models import ClusterConnection, sanitizer
from renku_data_services.notebooks.api.classes.auth import RenkuTokens
from renku_data_services.notebooks.api.classes.k8s_client import NotebookK8sClient
from renku_data_services.notebooks.util.kubernetes_ import find_env_var
from test.components.renku_data_services.crc_models.hypothesis import quota_strat, quota_strat_w_id


@pytest_asyncio.fixture(scope="session")
async def quota_repo(cluster):
    default_kubeconfig = await from_kubeconfig_file(cluster.kubeconfig)
    default_api = await default_kubeconfig.api()
    cluster_connection = ClusterConnection(id=DEFAULT_K8S_CLUSTER, namespace=default_api.namespace, api=default_api)
    clnt = K8sClusterClient(cluster_connection)
    rc_client = K8sResourceQuotaClient(clnt)
    pc_client = K8sSchedulingClient(clnt)
    yield QuotaRepository(rc_client, pc_client, namespace=default_api.namespace)


@given(quota=quota_strat)
@pytest.mark.xdist_group("sessions")
async def test_get_insert_quota(quota: models.UnsavedQuota, quota_repo: QuotaRepository) -> None:
    created_quota = await quota_repo.create_quota(quota, DEFAULT_K8S_CLUSTER)
    recovered_quota = await quota_repo.get_quota(created_quota.id, DEFAULT_K8S_CLUSTER)
    assert recovered_quota is not None
    assert created_quota.id == recovered_quota.id
    specific_quota_list = [q async for q in quota_repo.get_quotas(DEFAULT_K8S_CLUSTER, created_quota.id)]
    assert len(specific_quota_list) == 1
    specific_quota = specific_quota_list[0]
    assert specific_quota == created_quota


@settings(deadline=None, max_examples=5)
@given(quota=quota_strat)
@pytest.mark.xdist_group("sessions")
async def test_delete_quota(quota: models.UnsavedQuota, quota_repo: QuotaRepository) -> None:
    created_quota = await quota_repo.create_quota(quota, DEFAULT_K8S_CLUSTER)
    recovered_quota = await quota_repo.get_quota(created_quota.id, DEFAULT_K8S_CLUSTER)
    assert created_quota == recovered_quota
    await quota_repo.delete_quota(created_quota.id, DEFAULT_K8S_CLUSTER)
    # Kind needs some time for the deletion to propagate
    await asyncio.sleep(10)
    no_quota = await quota_repo.get_quota(created_quota.id, DEFAULT_K8S_CLUSTER)
    assert no_quota is None


@given(old_quota=quota_strat_w_id, new_quota=quota_strat)
@pytest.mark.xdist_group("sessions")
async def test_update_quota(
    old_quota: models.UnsavedQuota, new_quota: models.UnsavedQuota, quota_repo: QuotaRepository
) -> None:
    created_quota = None
    try:
        created_quota = await quota_repo.create_quota(old_quota, DEFAULT_K8S_CLUSTER)
        tmp = asdict(new_quota)
        tmp.pop("id", None)
        quota_update = models.Quota(**tmp, id=created_quota.id)
        updated_quota = await quota_repo.update_quota(quota_update, DEFAULT_K8S_CLUSTER)
        retrieved_quota = await quota_repo.get_quota(created_quota.id, DEFAULT_K8S_CLUSTER)
        assert updated_quota == retrieved_quota
    finally:
        if created_quota is not None:
            await quota_repo.delete_quota(created_quota.id, DEFAULT_K8S_CLUSTER)


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
    sanitized_sts = sanitizer(sts)
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
