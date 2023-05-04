import asyncio
from typing import List

from hypothesis import HealthCheck, given, settings

import models
from db.adapter import ResourcePoolRepository, UserRepository
from tests.unit.renku_crac.hypothesis import rp_list_strat, rp_strat, user_list_strat, user_strat
from tests.unit.renku_crac.utils import create_rp


@given(user=user_strat)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_insert_user(user_repo: UserRepository, user: models.User):
    inserted_user = asyncio.run(user_repo.insert_user(user))
    assert inserted_user is not None
    assert inserted_user.keycloak_id is not None
    retrieved_users = asyncio.run(user_repo.get_users(keycloak_id=user.keycloak_id))
    assert len(retrieved_users) == 1
    retrieved_user = retrieved_users[0]
    assert user.keycloak_id == retrieved_user.keycloak_id
    assert inserted_user == retrieved_user
    # NOTE: The db is not cleaned up for every sample of the fuzzy fixtures, so we clean up the users here
    asyncio.run(user_repo.delete_user(inserted_user.keycloak_id))


@given(user=user_strat)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_delete_user(user_repo: UserRepository, user: models.User):
    inserted_user = asyncio.run(user_repo.insert_user(user))
    assert inserted_user is not None
    assert inserted_user.keycloak_id is not None
    retrieved_users = asyncio.run(user_repo.get_users(keycloak_id=user.keycloak_id))
    assert len(retrieved_users) == 1
    asyncio.run(user_repo.delete_user(user.keycloak_id))
    retrieved_users = asyncio.run(user_repo.get_users(keycloak_id=user.keycloak_id))
    assert len(retrieved_users) == 0


@given(rp=rp_strat, users=user_list_strat)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_resource_pool_add_users(
    rp: models.ResourcePool, user_repo: UserRepository, pool_repo: ResourcePoolRepository, users: List[models.User]
):
    inserted_rp = create_rp(rp, pool_repo)
    assert inserted_rp.id is not None
    asyncio.run(user_repo.update_resource_pool_users(inserted_rp.id, users))
    retrieved_users = asyncio.run(user_repo.get_users(resource_pool_id=inserted_rp.id))
    assert len(retrieved_users) == len(users)
    retrieved_users_ids = [user.keycloak_id for user in retrieved_users]
    assert all([user.keycloak_id in retrieved_users_ids for user in users])
    a_user = users[0]
    asyncio.run(user_repo.update_resource_pool_users(inserted_rp.id, [a_user], append=False))
    retrieved_users = asyncio.run(user_repo.get_users(resource_pool_id=inserted_rp.id))
    assert len(retrieved_users) == 1
    assert retrieved_users[0].keycloak_id == a_user.keycloak_id
    # NOTE: The db is not cleaned up for every sample of the fuzzy fixtures, so we clean up the users here
    for user in users:
        asyncio.run(user_repo.delete_user(user.keycloak_id))


@given(rp=rp_strat, users=user_list_strat)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_resource_pool_remove_users(
    rp: models.ResourcePool, user_repo: UserRepository, pool_repo: ResourcePoolRepository, users: List[models.User]
):
    inserted_rp = create_rp(rp, pool_repo)
    assert inserted_rp.id is not None
    asyncio.run(user_repo.update_resource_pool_users(inserted_rp.id, users))
    original_users = asyncio.run(user_repo.get_users(resource_pool_id=inserted_rp.id))
    assert len(original_users) == len(users)
    remove_user = original_users[0]
    asyncio.run(user_repo.delete_resource_pool_user(inserted_rp.id, remove_user.keycloak_id))
    new_users = asyncio.run(user_repo.get_users(resource_pool_id=inserted_rp.id))
    assert remove_user not in new_users
    assert all([user in original_users for user in new_users])
    all_users = asyncio.run(user_repo.get_users())
    assert all([user in all_users for user in original_users])
    # NOTE: The db is not cleaned up for every sample of the fuzzy fixtures, so we clean up the users here
    for user in users:
        asyncio.run(user_repo.delete_user(user.keycloak_id))


@given(rps=rp_list_strat, user=user_strat)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
def test_get_update_user_resource_pools(
    rps: List[models.ResourcePool],
    user_repo: UserRepository,
    pool_repo: ResourcePoolRepository,
    user: models.User,
):
    inserted_rps = [create_rp(rp, pool_repo) for rp in rps]
    assert len(inserted_rps) == len(rps)
    inserted_user = asyncio.run(user_repo.insert_user(user))
    assert inserted_user is not None
    assert inserted_user.keycloak_id is not None
    user_rps = asyncio.run(user_repo.get_user_resource_pools(keycloak_id=inserted_user.keycloak_id))
    assert len(user_rps) == 0
    inserted_rp_ids = [rp.id for rp in inserted_rps if rp.id is not None]
    user_rps = asyncio.run(
        user_repo.update_user_resource_pools(keycloak_id=inserted_user.keycloak_id, resource_pool_ids=inserted_rp_ids)
    )
    assert len(user_rps) == len(inserted_rps)
    retrieved_user_rps = asyncio.run(user_repo.get_user_resource_pools(keycloak_id=inserted_user.keycloak_id))
    assert retrieved_user_rps == user_rps
    # NOTE: The db is not cleaned up for every sample of the fuzzy fixtures, so we clean up the users and rps here
    asyncio.run(user_repo.delete_user(inserted_user.keycloak_id))
    for rp in inserted_rps:
        if rp.id is not None:
            asyncio.run(pool_repo.delete_resource_pool(rp.id))
