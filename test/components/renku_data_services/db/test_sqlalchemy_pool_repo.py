import asyncio
from dataclasses import asdict
from test.components.renku_data_services.models.hypothesis import (
    a_name,
    a_uuid_string,
    private_rp_strat,
    public_rp_strat,
    rc_non_default_strat,
    rc_update_reqs_dict,
    rp_strat,
)
from test.utils import create_rp, remove_id_from_user

import pytest
import renku_data_services.resource_pool_models as models
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from renku_data_services.resource_pool_adapters import ResourcePoolRepository, UserRepository
from renku_data_services import errors


@given(rp=rp_strat())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
def test_resource_pool_insert_get(
    rp: models.ResourcePool, pool_repo: ResourcePoolRepository, admin_user: models.APIUser
):
    create_rp(rp, pool_repo, admin_user)


@given(rp=rp_strat(), new_name=a_name)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_resource_pool_update_name(
    rp: models.ResourcePool, pool_repo: ResourcePoolRepository, new_name: str, admin_user: models.APIUser
):
    inserted_rp = create_rp(rp, pool_repo, api_user=admin_user)
    assert inserted_rp.id is not None
    updated_rp = asyncio.run(pool_repo.update_resource_pool(id=inserted_rp.id, name=new_name, api_user=admin_user))
    assert updated_rp.id == inserted_rp.id
    assert updated_rp.name == new_name
    retrieved_rps = asyncio.run(pool_repo.get_resource_pools(id=inserted_rp.id, api_user=admin_user))
    assert len(retrieved_rps) == 1
    assert retrieved_rps[0] == updated_rp


@given(rp=rp_strat(), new_quota_id=a_uuid_string)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_resource_pool_update_quota(
    rp: models.ResourcePool, pool_repo: ResourcePoolRepository, new_quota_id: str, admin_user: models.APIUser
):
    inserted_rp = create_rp(rp, pool_repo, api_user=admin_user)
    assert inserted_rp.id is not None
    assert inserted_rp.quota is not None
    updated_rp = asyncio.run(pool_repo.update_resource_pool(id=inserted_rp.id, quota=new_quota_id, api_user=admin_user))
    assert updated_rp.id == inserted_rp.id
    assert updated_rp.quota is not None
    assert inserted_rp.quota != updated_rp.quota
    assert updated_rp.quota == new_quota_id
    retrieved_rps = asyncio.run(pool_repo.get_resource_pools(id=inserted_rp.id, api_user=admin_user))
    assert len(retrieved_rps) == 1
    assert retrieved_rps[0] == updated_rp


@given(rp=rp_strat(), data=st.data())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
def test_resource_pool_update_classes(
    rp: models.ResourcePool, pool_repo: ResourcePoolRepository, data, admin_user: models.APIUser
):
    inserted_rp = create_rp(rp, pool_repo, api_user=admin_user)
    assert inserted_rp.id is not None
    old_classes = [asdict(cls) for cls in list(inserted_rp.classes)]
    new_classes_dicts = [{**cls, **data.draw(rc_update_reqs_dict)} for cls in old_classes]
    new_classes_models = [models.ResourceClass(**cls) for cls in new_classes_dicts]
    updated_rp = asyncio.run(
        pool_repo.update_resource_pool(id=inserted_rp.id, classes=new_classes_dicts, api_user=admin_user)
    )
    assert updated_rp.id == inserted_rp.id
    assert len(updated_rp.classes) == len(inserted_rp.classes)
    assert updated_rp.classes == new_classes_models
    retrieved_rps = asyncio.run(pool_repo.get_resource_pools(id=inserted_rp.id, api_user=admin_user))
    assert len(retrieved_rps) == 1
    assert retrieved_rps[0] == updated_rp
    assert retrieved_rps[0].classes == updated_rp.classes


@given(rp=rp_strat())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_get_classes(rp: models.ResourcePool, pool_repo: ResourcePoolRepository, admin_user: models.APIUser):
    inserted_rp = create_rp(rp, pool_repo, api_user=admin_user)
    assert inserted_rp.id is not None
    retrieved_classes = asyncio.run(pool_repo.get_classes(resource_pool_id=inserted_rp.id, api_user=admin_user))
    assert retrieved_classes == inserted_rp.classes


@given(rp=rp_strat())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_get_class_by_id(rp: models.ResourcePool, pool_repo: ResourcePoolRepository, admin_user: models.APIUser):
    inserted_rp = create_rp(rp, pool_repo, api_user=admin_user)
    assert inserted_rp.id is not None
    a_class = inserted_rp.classes.copy().pop()
    assert a_class.id is not None
    retrieved_classes = asyncio.run(pool_repo.get_classes(id=a_class.id, api_user=admin_user))
    assert len(retrieved_classes) == 1
    assert retrieved_classes[0] == a_class


@given(rp=rp_strat())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_get_class_by_name(rp: models.ResourcePool, pool_repo: ResourcePoolRepository, admin_user: models.APIUser):
    inserted_rp = create_rp(rp, pool_repo, api_user=admin_user)
    assert inserted_rp.id is not None
    a_class = inserted_rp.classes.copy().pop()
    assert a_class.id is not None
    retrieved_classes = asyncio.run(pool_repo.get_classes(name=a_class.name, api_user=admin_user))
    assert len(retrieved_classes) >= 1
    assert any([a_class == cls for cls in retrieved_classes])


@given(rp=rp_strat())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_resource_pool_delete(rp: models.ResourcePool, pool_repo: ResourcePoolRepository, admin_user: models.APIUser):
    inserted_rp = create_rp(rp, pool_repo, api_user=admin_user)
    assert inserted_rp.id is not None
    asyncio.run(pool_repo.delete_resource_pool(id=inserted_rp.id, api_user=admin_user))
    retrieved_rps = asyncio.run(pool_repo.get_resource_pools(id=inserted_rp.id, api_user=admin_user))
    assert len(retrieved_rps) == 0


@given(rc=rc_non_default_strat(), rp=rp_strat())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_resource_class_create(
    rc: models.ResourceClass, rp: models.ResourcePool, pool_repo: ResourcePoolRepository, admin_user: models.APIUser
):
    inserted_rp = create_rp(rp, pool_repo, api_user=admin_user)
    assert inserted_rp.id is not None
    inserted_class = asyncio.run(
        pool_repo.insert_resource_class(resource_class=rc, resource_pool_id=inserted_rp.id, api_user=admin_user)
    )
    assert inserted_class is not None
    retrieved_rps = asyncio.run(pool_repo.get_resource_pools(id=inserted_rp.id, api_user=admin_user))
    assert len(retrieved_rps) == 1
    retrieved_rp = retrieved_rps[0]
    assert len(retrieved_rp.classes) >= 1
    assert set(retrieved_rp.classes).issuperset(
        {inserted_class}
    ), f"class {inserted_class} should be in {retrieved_rp.classes}"


@given(rp=rp_strat())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_resource_class_delete(rp: models.ResourcePool, pool_repo: ResourcePoolRepository, admin_user: models.APIUser):
    inserted_rp = create_rp(rp, pool_repo, api_user=admin_user)
    assert inserted_rp.id is not None
    assert len(inserted_rp.classes) > 0
    non_default_rc = [cls for cls in inserted_rp.classes if not cls.default]
    assert len(non_default_rc) > 0
    removed_cls = non_default_rc[0]
    assert removed_cls.id is not None
    asyncio.run(
        pool_repo.delete_resource_class(
            resource_pool_id=inserted_rp.id, resource_class_id=removed_cls.id, api_user=admin_user
        )
    )
    retrieved_rps = asyncio.run(pool_repo.get_resource_pools(id=inserted_rp.id, api_user=admin_user))
    assert len(retrieved_rps) == 1
    retrieved_rp = retrieved_rps[0]
    assert not set(retrieved_rp.classes).issuperset(
        {removed_cls}
    ), f"class {removed_cls} should not be in {retrieved_rp.classes}"


@given(rp=rp_strat(), rc_update=rc_update_reqs_dict)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_resource_class_update(
    rp: models.ResourcePool, pool_repo: ResourcePoolRepository, admin_user: models.APIUser, rc_update: dict
):
    inserted_rp = asyncio.run(pool_repo.insert_resource_pool(resource_pool=rp, api_user=admin_user))
    assert inserted_rp is not None
    assert inserted_rp.id is not None
    assert len(inserted_rp.classes) > 0
    default_rcs = [cls for cls in inserted_rp.classes if cls.default]
    assert len(default_rcs) == 1
    rc_to_update = default_rcs[0]
    assert rc_to_update.id is not None
    new_rc_dict = asdict(rc_to_update)
    for k, v in rc_update.items():
        new_rc_dict[k] += v
    new_rc_dict.pop("id")
    updated_rc = asyncio.run(
        pool_repo.update_resource_class(
            resource_pool_id=inserted_rp.id, resource_class_id=rc_to_update.id, api_user=admin_user, **new_rc_dict
        )
    )
    retrieved_rps = asyncio.run(pool_repo.get_resource_pools(id=inserted_rp.id, api_user=admin_user))
    assert len(retrieved_rps) == 1
    retrieved_rp = retrieved_rps[0]
    assert updated_rc.id == rc_to_update.id
    assert set(retrieved_rp.classes).issuperset({updated_rc}), f"class {updated_rc} should be in {retrieved_rp.classes}"
    assert not set(retrieved_rp.classes).issuperset(
        {rc_to_update}
    ), f"class {rc_to_update} should not be in {retrieved_rp.classes}"


@given(rp=rp_strat())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_lookup_rp_by_name(rp: models.ResourcePool, pool_repo: ResourcePoolRepository, admin_user: models.APIUser):
    inserted_rp = create_rp(rp, pool_repo, api_user=admin_user)
    assert inserted_rp.id is not None
    retrieved_rps = asyncio.run(pool_repo.get_resource_pools(name=inserted_rp.name, api_user=admin_user))
    assert len(retrieved_rps) >= 1
    assert any([rp == inserted_rp for rp in retrieved_rps])


@given(rc=rc_non_default_strat())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_insert_class_in_nonexisting_rp(
    pool_repo: ResourcePoolRepository, rc: models.ResourceClass, admin_user: models.APIUser
):
    with pytest.raises(errors.MissingResourceError):
        asyncio.run(pool_repo.insert_resource_class(resource_class=rc, resource_pool_id=99999, api_user=admin_user))


@given(new_quota_id=a_uuid_string)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_update_quota_in_nonexisting_rp(
    pool_repo: ResourcePoolRepository, new_quota_id: str, admin_user: models.APIUser
):
    with pytest.raises(errors.MissingResourceError):
        asyncio.run(pool_repo.update_resource_pool(id=99999, api_user=admin_user, quota=new_quota_id))


@given(public_rp=public_rp_strat, private_rp=private_rp_strat)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
def test_resource_pools_access_control(
    public_rp: models.ResourcePool,
    private_rp: models.ResourcePool,
    admin_user: models.APIUser,
    loggedin_user: models.APIUser,
    pool_repo: ResourcePoolRepository,
    user_repo: UserRepository,
):
    inserted_public_rp = create_rp(public_rp, pool_repo, admin_user)
    assert inserted_public_rp.id is not None
    inserted_private_rp = create_rp(private_rp, pool_repo, admin_user)
    assert inserted_public_rp.id is not None
    admin_rps = asyncio.run(pool_repo.get_resource_pools(admin_user))
    loggedin_user_rps = asyncio.run(pool_repo.get_resource_pools(loggedin_user))
    assert inserted_public_rp in loggedin_user_rps
    assert inserted_public_rp in admin_rps
    assert inserted_private_rp not in loggedin_user_rps
    assert inserted_private_rp in admin_rps
    assert loggedin_user.id is not None
    user_to_add = models.User(keycloak_id=loggedin_user.id)
    updated_users = asyncio.run(
        user_repo.update_resource_pool_users(admin_user, inserted_private_rp.id, [user_to_add], append=True)
    )
    assert user_to_add in [remove_id_from_user(user) for user in updated_users]
    loggedin_user_rps = asyncio.run(pool_repo.get_resource_pools(loggedin_user))
    assert inserted_private_rp in loggedin_user_rps


@given(rp1=rp_strat(), rp2=rp_strat())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_classes_filtering(
    rp1: models.ResourcePool, rp2: models.ResourcePool, pool_repo: ResourcePoolRepository, admin_user: models.APIUser
):
    inserted_rp1 = create_rp(rp1, pool_repo, api_user=admin_user)
    inserted_rp2 = create_rp(rp2, pool_repo, api_user=admin_user)
    assert inserted_rp1.id is not None
    assert inserted_rp2.id is not None
    all_rps = asyncio.run(pool_repo.get_resource_pools(admin_user))
    assert len(all_rps) == 2
    assert len(all_rps[0].classes) + len(all_rps[1].classes) == len(inserted_rp1.classes) + len(inserted_rp2.classes)
    cpu_filter = 1
    memory_filter = 4
    filtered_resource_pools = asyncio.run(
        pool_repo.filter_resource_pools(admin_user, cpu=cpu_filter, memory=memory_filter)
    )
    assert len(filtered_resource_pools) == 2
    assert len(filtered_resource_pools[0].classes) + len(filtered_resource_pools[1].classes) == len(
        inserted_rp1.classes
    ) + len(inserted_rp2.classes)
    expected_matches = [
        cls for cls in inserted_rp1.classes if cls.cpu >= cpu_filter and cls.memory >= memory_filter
    ] + [cls for cls in inserted_rp2.classes if cls.cpu >= cpu_filter and cls.memory >= memory_filter]
    assert len(expected_matches) == len(
        [i for i in filtered_resource_pools[0].classes if i.matching]
        + [i for i in filtered_resource_pools[1].classes if i.matching]
    )
    asyncio.run(pool_repo.delete_resource_pool(admin_user, inserted_rp1.id))
    asyncio.run(pool_repo.delete_resource_pool(admin_user, inserted_rp2.id))
