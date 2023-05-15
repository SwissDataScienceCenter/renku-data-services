import asyncio
from dataclasses import asdict

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import models
from db.adapter import ResourcePoolRepository
from models import errors
from tests.unit.renku_crac.hypothesis import a_name, quota_strat, rc_non_default_strat, rc_update_reqs_dict, rp_strat
from tests.unit.renku_crac.utils import create_rp, remove_id_from_rp


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


@given(rp=rp_strat(), new_quota=quota_strat)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_resource_pool_update_quota(
    rp: models.ResourcePool, pool_repo: ResourcePoolRepository, new_quota: models.Quota, admin_user: models.APIUser
):
    inserted_rp = create_rp(rp, pool_repo, api_user=admin_user)
    assert inserted_rp.id is not None
    assert inserted_rp.quota is not None
    new_quota_dict = asdict(new_quota)
    new_quota_dict.pop("id")
    updated_rp = asyncio.run(
        pool_repo.update_resource_pool(id=inserted_rp.id, quota=new_quota_dict, api_user=admin_user)
    )
    assert updated_rp.id == inserted_rp.id
    assert updated_rp.quota is not None
    updated_rp_no_ids = remove_id_from_rp(updated_rp)
    assert inserted_rp.quota.id == updated_rp.quota.id
    assert updated_rp_no_ids.quota == new_quota
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
    new_classes_models = set([models.ResourceClass(**cls) for cls in new_classes_dicts])
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
    assert set(retrieved_classes) == inserted_rp.classes


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
    assert retrieved_rp.classes.issuperset(
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
    assert not retrieved_rp.classes.issuperset(
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
    new_rc_dict.update(**rc_update)
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
    assert retrieved_rp.classes.issuperset({updated_rc}), f"class {updated_rc} should be in {retrieved_rp.classes}"
    assert not retrieved_rp.classes.issuperset(
        {rc_to_update}
    ), f"class {rc_to_update} should not be in {retrieved_rp.classes}"


@given(rp=rp_strat())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_get_quota(rp: models.ResourcePool, pool_repo: ResourcePoolRepository, admin_user: models.APIUser):
    inserted_rp = create_rp(rp, pool_repo, api_user=admin_user)
    assert inserted_rp.id is not None
    retrieved_quota = asyncio.run(pool_repo.get_quota(resource_pool_id=inserted_rp.id, api_user=admin_user))
    assert retrieved_quota is not None
    assert retrieved_quota == inserted_rp.quota


@given(rp=rp_strat())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_quota_update(rp: models.ResourcePool, pool_repo: ResourcePoolRepository, admin_user: models.APIUser):
    inserted_rp = create_rp(rp, pool_repo, api_user=admin_user)
    assert inserted_rp.id is not None
    old_quota = inserted_rp.quota
    new_quota = models.Quota(9999999, 9999999, 9999999, 9999999)
    new_quota_dict = asdict(new_quota)
    new_quota_dict.pop("id")
    updated_quota = asyncio.run(
        pool_repo.update_quota(resource_pool_id=inserted_rp.id, api_user=admin_user, **new_quota_dict)
    )
    retrieved_rps = asyncio.run(pool_repo.get_resource_pools(id=inserted_rp.id, api_user=admin_user))
    assert len(retrieved_rps) == 1
    retrieved_rp = retrieved_rps[0]
    assert updated_quota != old_quota
    assert retrieved_rp.quota == updated_quota


@given(rp=rp_strat())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_lookup_rp_by_name(rp: models.ResourcePool, pool_repo: ResourcePoolRepository, admin_user: models.APIUser):
    inserted_rp = create_rp(rp, pool_repo, api_user=admin_user)
    assert inserted_rp.id is not None
    retrieved_rps = asyncio.run(pool_repo.get_resource_pools(name=inserted_rp.name, api_user=admin_user))
    assert len(retrieved_rps) >= 1
    assert any([rp == inserted_rp for rp in retrieved_rps])


@given(rc=rc_non_default_strat())
def insert_class_in_nonexisting_rp(
    pool_repo: ResourcePoolRepository, rc: models.ResourceClass, admin_user: models.APIUser
):
    with pytest.raises(errors.MissingResourceError):
        asyncio.run(pool_repo.insert_resource_class(resource_class=rc, resource_pool_id=99999, api_user=admin_user))


@given(quota=quota_strat)
def update_quota_in_nonexisting_rp(pool_repo: ResourcePoolRepository, quota: models.Quota, admin_user: models.APIUser):
    with pytest.raises(errors.MissingResourceError):
        quota_dict = asdict(quota)
        quota_dict.pop("id")
        asyncio.run(pool_repo.update_quota(resource_pool_id=99999, api_user=admin_user, **quota_dict))
