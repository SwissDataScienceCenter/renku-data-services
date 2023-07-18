import asyncio
from test.components.renku_data_services.models.hypothesis import rp_list_strat, rp_strat, user_list_strat, user_strat
from test.utils import create_rp
from typing import List

import renku_data_services.models.crc as models
from hypothesis import HealthCheck, given, settings
from renku_data_services.db.adapter import ResourcePoolRepository, UserRepository


@given(user=user_strat)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
def test_insert_user(user_repo: UserRepository, user: models.User, admin_user: models.APIUser):
    inserted_user = asyncio.run(user_repo.insert_user(user=user, api_user=admin_user))
    assert inserted_user is not None
    assert inserted_user.keycloak_id is not None
    retrieved_users = asyncio.run(user_repo.get_users(keycloak_id=user.keycloak_id, api_user=admin_user))
    assert len(retrieved_users) == 1
    retrieved_user = retrieved_users[0]
    assert user.keycloak_id == retrieved_user.keycloak_id
    assert inserted_user == retrieved_user
    # NOTE: The db is not cleaned up for every sample of the fuzzy fixtures, so we clean up the users here
    asyncio.run(user_repo.delete_user(id=inserted_user.keycloak_id, api_user=admin_user))


@given(user=user_strat)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
def test_delete_user(user_repo: UserRepository, user: models.User, admin_user: models.APIUser):
    inserted_user = asyncio.run(user_repo.insert_user(user=user, api_user=admin_user))
    assert inserted_user is not None
    assert inserted_user.keycloak_id is not None
    retrieved_users = asyncio.run(user_repo.get_users(keycloak_id=user.keycloak_id, api_user=admin_user))
    assert len(retrieved_users) == 1
    asyncio.run(user_repo.delete_user(id=user.keycloak_id, api_user=admin_user))
    retrieved_users = asyncio.run(user_repo.get_users(keycloak_id=user.keycloak_id, api_user=admin_user))
    assert len(retrieved_users) == 0


@given(rp=rp_strat(), users=user_list_strat)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
def test_resource_pool_add_users(
    rp: models.ResourcePool,
    user_repo: UserRepository,
    pool_repo: ResourcePoolRepository,
    users: List[models.User],
    admin_user: models.APIUser,
):
    inserted_rp = create_rp(rp, pool_repo, api_user=admin_user)
    assert inserted_rp.id is not None
    asyncio.run(user_repo.update_resource_pool_users(resource_pool_id=inserted_rp.id, users=users, api_user=admin_user))
    retrieved_users = asyncio.run(user_repo.get_users(resource_pool_id=inserted_rp.id, api_user=admin_user))
    assert len(retrieved_users) == len(users)
    retrieved_users_ids = [user.keycloak_id for user in retrieved_users]
    assert all([user.keycloak_id in retrieved_users_ids for user in users])
    a_user = users[0]
    asyncio.run(
        user_repo.update_resource_pool_users(
            resource_pool_id=inserted_rp.id, users=[a_user], append=False, api_user=admin_user
        )
    )
    retrieved_users = asyncio.run(user_repo.get_users(resource_pool_id=inserted_rp.id, api_user=admin_user))
    assert len(retrieved_users) == 1
    assert retrieved_users[0].keycloak_id == a_user.keycloak_id
    # NOTE: The db is not cleaned up for every sample of the fuzzy fixtures, so we clean up the users here
    for user in users:
        asyncio.run(user_repo.delete_user(id=user.keycloak_id, api_user=admin_user))


@given(rp=rp_strat(), users=user_list_strat)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
def test_resource_pool_remove_users(
    rp: models.ResourcePool,
    user_repo: UserRepository,
    pool_repo: ResourcePoolRepository,
    users: List[models.User],
    admin_user: models.APIUser,
):
    inserted_rp = create_rp(rp, pool_repo, api_user=admin_user)
    assert inserted_rp.id is not None
    asyncio.run(user_repo.update_resource_pool_users(resource_pool_id=inserted_rp.id, users=users, api_user=admin_user))
    original_users = asyncio.run(user_repo.get_users(resource_pool_id=inserted_rp.id, api_user=admin_user))
    assert len(original_users) == len(users)
    remove_user = original_users[0]
    asyncio.run(
        user_repo.delete_resource_pool_user(
            resource_pool_id=inserted_rp.id, keycloak_id=remove_user.keycloak_id, api_user=admin_user
        )
    )
    new_users = asyncio.run(user_repo.get_users(resource_pool_id=inserted_rp.id, api_user=admin_user))
    assert remove_user not in new_users
    assert all([user in original_users for user in new_users])
    all_users = asyncio.run(user_repo.get_users(api_user=admin_user))
    assert all([user in all_users for user in original_users])
    # NOTE: The db is not cleaned up for every sample of the fuzzy fixtures, so we clean up the users here
    for user in users:
        asyncio.run(user_repo.delete_user(id=user.keycloak_id, api_user=admin_user))


@given(rps=rp_list_strat, user=user_strat)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
def test_get_update_user_resource_pools(
    rps: List[models.ResourcePool],
    user_repo: UserRepository,
    pool_repo: ResourcePoolRepository,
    user: models.User,
    admin_user: models.APIUser,
):
    inserted_rps = [create_rp(rp, pool_repo, api_user=admin_user) for rp in rps]
    assert len(inserted_rps) == len(rps)
    inserted_user = asyncio.run(user_repo.insert_user(user=user, api_user=admin_user))
    assert inserted_user is not None
    assert inserted_user.keycloak_id is not None
    user_rps = asyncio.run(
        user_repo.get_user_resource_pools(keycloak_id=inserted_user.keycloak_id, api_user=admin_user)
    )
    assert len(user_rps) == 0
    inserted_rp_ids = [rp.id for rp in inserted_rps if rp.id is not None]
    user_rps = asyncio.run(
        user_repo.update_user_resource_pools(
            keycloak_id=inserted_user.keycloak_id, resource_pool_ids=inserted_rp_ids, api_user=admin_user
        )
    )
    assert len(user_rps) == len(inserted_rps)
    retrieved_user_rps = asyncio.run(
        user_repo.get_user_resource_pools(keycloak_id=inserted_user.keycloak_id, api_user=admin_user)
    )
    assert retrieved_user_rps == user_rps
    # NOTE: The db is not cleaned up for every sample of the fuzzy fixtures, so we clean up the users and rps here
    asyncio.run(user_repo.delete_user(id=inserted_user.keycloak_id, api_user=admin_user))
    for rp in inserted_rps:
        if rp.id is not None:
            asyncio.run(pool_repo.delete_resource_pool(id=rp.id, api_user=admin_user))
