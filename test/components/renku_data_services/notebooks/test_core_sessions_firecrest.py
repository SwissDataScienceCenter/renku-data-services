"""Unit tests for FirecREST remote session env helpers."""

from renku_data_services.crc.models import (
    FirecrestClassRemote,
    RemoteConfigurationFirecrest,
    ResourceClass,
)
from renku_data_services.notebooks.core_sessions import _firecrest_resource_env_items


def test_firecrest_resource_env_items_forwards_false_by_default():
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
    )
    env = _firecrest_resource_env_items(resource_class, pool_remote)
    by_name = {item.name: item.value for item in env}
    assert by_name["RSC_FIRECREST_SYSTEM_NAME"] == "pool-system"
    assert by_name["RSC_FIRECREST_PARTITION"] == "pool-partition"
    assert by_name["RSC_FIRECREST_FORWARD_RESOURCE_VALUES"] == "false"


def test_firecrest_resource_env_items_use_class_overrides():
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
        remote=FirecrestClassRemote(system_name="class-system", partition="class-partition"),
    )
    env = _firecrest_resource_env_items(resource_class, pool_remote)
    by_name = {item.name: item.value for item in env}
    assert by_name["RSC_FIRECREST_SYSTEM_NAME"] == "class-system"
    assert by_name["RSC_FIRECREST_PARTITION"] == "class-partition"
    assert by_name["RSC_FIRECREST_FORWARD_RESOURCE_VALUES"] == "false"


def test_firecrest_resource_env_items_fall_back_to_pool_values():
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
    )
    env = _firecrest_resource_env_items(resource_class, pool_remote)
    by_name = {item.name: item.value for item in env}
    assert by_name["RSC_FIRECREST_SYSTEM_NAME"] == "pool-system"
    assert by_name["RSC_FIRECREST_PARTITION"] == "pool-partition"
    assert by_name["RSC_FIRECREST_FORWARD_RESOURCE_VALUES"] == "false"


def test_firecrest_resource_env_items_forwards_true_when_set():
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
        remote=FirecrestClassRemote(forward_resource_values=True),
    )
    env = _firecrest_resource_env_items(resource_class, pool_remote)
    by_name = {item.name: item.value for item in env}
    assert by_name["RSC_FIRECREST_SYSTEM_NAME"] == "pool-system"
    assert by_name["RSC_FIRECREST_PARTITION"] == "pool-partition"
    assert by_name["RSC_FIRECREST_FORWARD_RESOURCE_VALUES"] == "true"
