"""Unit tests for FirecREST remote session env helpers."""

from renku_data_services.crc.models import (
    FirecrestClassRemote,
    RemoteConfigurationFirecrest,
    RemoteConfigurationKind,
    ResourceClass,
)
from renku_data_services.notebooks.core_sessions import (
    _effective_firecrest_remote,
    _firecrest_resource_env_items,
    get_remote_env,
)


def test_effective_firecrest_remote_uses_class_overrides():
    pool_remote = RemoteConfigurationFirecrest(
        api_url="https://pool.example.org",
        system_name="pool-system",
        partition="pool-partition",
        provider_id="p1",
    )
    resource_class = ResourceClass(
        id=1,
        name="class",
        cpu=4,
        memory=8,
        gpu=1,
        max_storage=100,
        kind=RemoteConfigurationKind.firecrest,
        remote=FirecrestClassRemote(system_name="class-system", partition="class-partition"),
    )
    system_name, partition = _effective_firecrest_remote(resource_class, pool_remote)
    assert system_name == "class-system"
    assert partition == "class-partition"


def test_effective_firecrest_remote_falls_back_to_pool():
    pool_remote = RemoteConfigurationFirecrest(
        api_url="https://pool.example.org",
        system_name="pool-system",
        partition="pool-partition",
        provider_id="p1",
    )
    resource_class = ResourceClass(
        id=1,
        name="class",
        cpu=2,
        memory=4,
        gpu=0,
        max_storage=100,
        kind=RemoteConfigurationKind.firecrest,
    )
    system_name, partition = _effective_firecrest_remote(resource_class, pool_remote)
    assert system_name == "pool-system"
    assert partition == "pool-partition"


def test_effective_firecrest_remote_omits_partition_when_none():
    pool_remote = RemoteConfigurationFirecrest(
        api_url="https://pool.example.org",
        system_name="pool-system",
        provider_id="p1",
    )
    resource_class = ResourceClass(
        id=1,
        name="class",
        cpu=2,
        memory=4,
        gpu=0,
        max_storage=100,
        kind=RemoteConfigurationKind.firecrest,
    )
    system_name, partition = _effective_firecrest_remote(resource_class, pool_remote)
    assert system_name == "pool-system"
    assert partition is None


def test_firecrest_resource_env_items_omit_resource_values_by_default():
    pool_remote = RemoteConfigurationFirecrest(
        api_url="https://pool.example.org",
        system_name="pool-system",
        partition="pool-partition",
        provider_id="p1",
    )
    resource_class = ResourceClass(
        id=1,
        name="class",
        cpu=4,
        memory=8,
        gpu=1,
        max_storage=100,
        kind=RemoteConfigurationKind.firecrest,
    )
    env = _firecrest_resource_env_items(resource_class, pool_remote)
    by_name = {item.name: item.value for item in env}
    assert by_name["RSC_FIRECREST_SYSTEM_NAME"] == "pool-system"
    assert by_name["RSC_FIRECREST_PARTITION"] == "pool-partition"
    assert "RSC_FIRECREST_IGNORE_RESOURCE_CLASS_VALUES" not in by_name


def test_firecrest_resource_env_items_emits_ignore_flag_when_set():
    pool_remote = RemoteConfigurationFirecrest(
        api_url="https://pool.example.org",
        system_name="pool-system",
        partition="pool-partition",
        provider_id="p1",
    )
    resource_class = ResourceClass(
        id=1,
        name="class",
        cpu=4,
        memory=8,
        gpu=1,
        max_storage=100,
        kind=RemoteConfigurationKind.firecrest,
        remote=FirecrestClassRemote(ignore_resource_class_values=True),
    )
    env = _firecrest_resource_env_items(resource_class, pool_remote)
    by_name = {item.name: item.value for item in env}
    assert "RSC_FIRECREST_CPUS_PER_TASK" not in by_name
    assert "RSC_FIRECREST_MEM" not in by_name
    assert "RSC_FIRECREST_GPUS" not in by_name
    assert by_name["RSC_FIRECREST_SYSTEM_NAME"] == "pool-system"
    assert by_name["RSC_FIRECREST_PARTITION"] == "pool-partition"
    assert by_name["RSC_FIRECREST_IGNORE_RESOURCE_CLASS_VALUES"] == "true"


def test_get_remote_env():
    remote = RemoteConfigurationFirecrest(
        api_url="https://example.org",
        system_name="sys",
        partition="normal",
        provider_id="p1",
    )
    env = get_remote_env(remote)
    by_name = {item.name: item.value for item in env}
    assert by_name == {
        "RSC_REMOTE_KIND": RemoteConfigurationKind.firecrest.value,
        "RSC_FIRECREST_API_URL": "https://example.org",
    }
