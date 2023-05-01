import asyncio
from dataclasses import asdict
from typing import List

import pytest
from hypothesis import given, strategies as st, settings, HealthCheck

from src.db.adapter import DB
from src import models

SQL_BIGINT_MAX = 9_223_372_036_854_775_807
a_cpu = st.floats(min_value=0.0)
a_gpu = st.integers(min_value=0, max_value=SQL_BIGINT_MAX)
a_storage = st.integers(min_value=0, max_value=SQL_BIGINT_MAX)
a_memory = st.integers(min_value=0, max_value=SQL_BIGINT_MAX)
a_row_id = st.integers(min_value=1, max_value=SQL_BIGINT_MAX)
a_name = st.text(min_size=5)
a_uuid_string = st.uuids(version=4).map(lambda x: str(x))

rc_strat = st.builds(models.ResourceClass, name=a_name, cpu=a_cpu, gpu=a_gpu, storage=a_storage, memory=a_memory)
rc_set_strat = st.sets(rc_strat)
quota_strat = st.builds(models.Quota, cpu=a_cpu, gpu=a_gpu, storage=a_storage, memory=a_memory)
rp_strat = st.builds(models.ResourcePool, name=a_name, quota=quota_strat, classes=rc_set_strat)
user_strat = st.builds(models.User, username=st.emails(), keycloak_id=a_uuid_string)
user_list_strat = st.lists(user_strat, max_size=5, min_size=1)


@pytest.fixture
def db_instance(sqlite_file_url_sync, sqlite_file_url_async, monkeypatch):
    db = DB(sqlite_file_url_sync, sqlite_file_url_async)
    monkeypatch.setenv("ASYNC_SQLALCHEMY_URL", sqlite_file_url_async)
    monkeypatch.setenv("SYNC_SQLALCHEMY_URL", sqlite_file_url_sync)
    db.do_migrations()
    monkeypatch.delenv("ASYNC_SQLALCHEMY_URL")
    monkeypatch.delenv("SYNC_SQLALCHEMY_URL")
    yield db
    monkeypatch.delenv("ASYNC_SQLALCHEMY_URL", raising=False)
    monkeypatch.delenv("SYNC_SQLALCHEMY_URL", raising=False)


def remove_id_from_quota(quota: models.Quota) -> models.Quota:
    kwargs = asdict(quota)
    kwargs["id"] = None
    return models.Quota(**kwargs)


def remove_id_from_rc(rc: models.ResourceClass) -> models.ResourceClass:
    kwargs = asdict(rc)
    kwargs["id"] = None
    return models.ResourceClass(**kwargs)


def remove_id_from_rp(rp: models.ResourcePool) -> models.ResourcePool:
    quota = None
    if rp.quota is not None:
        quota = remove_id_from_quota(rp.quota)
    classes = set([remove_id_from_rc(rc) for rc in rp.classes])
    return models.ResourcePool(name=rp.name, id=None, quota=quota, classes=classes)


def remove_id_from_user(user: models.User) -> models.User:
    kwargs = asdict(user)
    kwargs["id"] = None
    return models.User(**kwargs)


@given(rp=rp_strat)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_resource_pool_insert_get(rp: models.ResourcePool, db_instance: DB):
    inserted_rp = asyncio.run(db_instance.insert_resource_pool(rp))
    assert inserted_rp.id is not None
    assert inserted_rp.quota is not None
    assert inserted_rp.quota.id is not None
    assert all([rc.id is not None for rc in inserted_rp.classes])
    inserted_ip_noids = remove_id_from_rp(inserted_rp)
    assert inserted_ip_noids == rp
    retrieved_rps = asyncio.run(db_instance.get_resource_pools(inserted_rp.id))
    assert len(retrieved_rps) == 1
    retrieved_rp = retrieved_rps[0]
    assert inserted_rp == retrieved_rp


@given(rp=rp_strat)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_resource_pool_delete(rp: models.ResourcePool, db_instance: DB):
    inserted_rp = asyncio.run(db_instance.insert_resource_pool(rp))
    assert inserted_rp is not None
    assert inserted_rp.id is not None
    retrieved_rps = asyncio.run(db_instance.get_resource_pools(inserted_rp.id))
    assert len(retrieved_rps) == 1
    asyncio.run(db_instance.delete_resource_pool(inserted_rp.id))
    retrieved_rps = asyncio.run(db_instance.get_resource_pools(inserted_rp.id))
    assert len(retrieved_rps) == 0


@given(rp=rp_strat, users=user_list_strat)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_resource_pool_add_users(rp: models.ResourcePool, db_instance: DB, users: List[models.User]):
    inserted_rp = asyncio.run(db_instance.insert_resource_pool(rp))
    assert inserted_rp is not None
    assert inserted_rp.id is not None
    asyncio.run(db_instance.update_resource_pool_users(inserted_rp.id, users))
    retrieved_users = asyncio.run(db_instance.get_users(resource_pool_id=inserted_rp.id))
    assert len(retrieved_users) == len(users)
    retrieved_users_ids = [user.keycloak_id for user in retrieved_users]
    assert all([user.keycloak_id in retrieved_users_ids for user in users])
    a_user = users[0]
    asyncio.run(db_instance.update_resource_pool_users(inserted_rp.id, [a_user], append=False))
    retrieved_users = asyncio.run(db_instance.get_users(resource_pool_id=inserted_rp.id))
    assert len(retrieved_users) == 1
    assert retrieved_users[0].keycloak_id == a_user.keycloak_id

@given(rp=rp_strat, users=user_list_strat)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_resource_pool_remove_users(rp: models.ResourcePool, db_instance: DB, users: List[models.User]):
    inserted_rp = asyncio.run(db_instance.insert_resource_pool(rp))
    assert inserted_rp is not None
    assert inserted_rp.id is not None
    asyncio.run(db_instance.update_resource_pool_users(inserted_rp.id, users))
    original_users = asyncio.run(db_instance.get_users(resource_pool_id=inserted_rp.id))
    assert len(original_users) == len(users)
    remove_user = original_users[0]
    asyncio.run(db_instance.delete_resource_pool_user(inserted_rp.id, remove_user.keycloak_id))
    new_users = asyncio.run(db_instance.get_users(resource_pool_id=inserted_rp.id))
    assert remove_user not in new_users
    assert all([user in original_users for user in new_users])
    all_users = asyncio.run(db_instance.get_users())
    assert all([user in all_users for user in original_users])
