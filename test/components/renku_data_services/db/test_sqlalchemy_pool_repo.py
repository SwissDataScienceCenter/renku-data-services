from dataclasses import asdict
from test.components.renku_data_services.crc_models.hypothesis import (
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
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.app_config import Config
from renku_data_services.crc import models


@given(rp=rp_strat())
@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@pytest.mark.asyncio
async def test_resource_pool_insert_get(rp: models.ResourcePool, app_config: Config, admin_user: base_models.APIUser):
    inserted_rp = None
    pool_repo = app_config.rp_repo
    try:
        inserted_rp = await create_rp(rp, pool_repo, admin_user)
    except (ValidationError, errors.ValidationError):
        pass
    finally:
        if inserted_rp is not None:
            await pool_repo.delete_resource_pool(admin_user, inserted_rp.id)


@given(rp=rp_strat(), new_name=a_name)
@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@pytest.mark.asyncio
async def test_resource_pool_update_name(
    rp: models.ResourcePool, app_config: Config, new_name: str, admin_user: base_models.APIUser
):
    inserted_rp = None
    pool_repo = app_config.rp_repo
    try:
        inserted_rp = await create_rp(rp, pool_repo, api_user=admin_user)
        assert inserted_rp.id is not None
        updated_rp = await pool_repo.update_resource_pool(id=inserted_rp.id, name=new_name, api_user=admin_user)
        assert updated_rp.id == inserted_rp.id
        assert updated_rp.name == new_name
        retrieved_rps = await pool_repo.get_resource_pools(id=inserted_rp.id, api_user=admin_user)
        assert len(retrieved_rps) == 1
        assert retrieved_rps[0] == updated_rp
    except (ValidationError, errors.ValidationError):
        pass
    finally:
        if inserted_rp is not None:
            await pool_repo.delete_resource_pool(admin_user, inserted_rp.id)


@given(rp=rp_strat())
@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@pytest.mark.asyncio
async def test_resource_pool_update_quota(rp: models.ResourcePool, app_config: Config, admin_user: base_models.APIUser):
    pool_repo = app_config.rp_repo
    try:
        inserted_rp = await create_rp(rp, pool_repo, api_user=admin_user)
        assert inserted_rp.id is not None
        assert inserted_rp.quota is not None
        updated_rp = await pool_repo.update_resource_pool(
            id=inserted_rp.id,
            quota={"cpu": 999, "memory": 999, "gpu": 999},
            api_user=admin_user,
        )
        assert updated_rp.id == inserted_rp.id
        assert updated_rp.quota is not None
        assert inserted_rp.quota != updated_rp.quota
        assert inserted_rp.quota.id == updated_rp.quota.id
        assert updated_rp.quota.cpu == 999
        assert updated_rp.quota.memory == 999
        assert updated_rp.quota.gpu == 999
        retrieved_rps = await pool_repo.get_resource_pools(id=inserted_rp.id, api_user=admin_user)
        assert len(retrieved_rps) == 1
        assert retrieved_rps[0] == updated_rp
    except (ValidationError, errors.ValidationError):
        pass


@given(rp=rp_strat(), data=st.data())
@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@pytest.mark.asyncio
async def test_resource_pool_update_classes(
    rp: models.ResourcePool, app_config: Config, data, admin_user: base_models.APIUser
):
    inserted_rp = None
    pool_repo = app_config.rp_repo
    try:
        inserted_rp = await create_rp(rp, pool_repo, api_user=admin_user)
        assert inserted_rp.id is not None
        old_classes = [asdict(cls) for cls in list(inserted_rp.classes)]
        new_classes_dicts = [{**cls, **data.draw(rc_update_reqs_dict)} for cls in old_classes]
        new_classes_models = [models.ResourceClass.from_dict(cls) for cls in new_classes_dicts]
        new_classes_models = sorted(
            new_classes_models, key=lambda x: (x.default, x.cpu, x.memory, x.default_storage, x.name)
        )

        updated_rp = await pool_repo.update_resource_pool(
            id=inserted_rp.id, classes=new_classes_dicts, api_user=admin_user
        )

        assert updated_rp.id == inserted_rp.id
        assert len(updated_rp.classes) == len(inserted_rp.classes)
        assert updated_rp.classes == new_classes_models
        retrieved_rps = await pool_repo.get_resource_pools(id=inserted_rp.id, api_user=admin_user)
        assert len(retrieved_rps) == 1
        assert retrieved_rps[0] == updated_rp
        assert retrieved_rps[0].classes == updated_rp.classes
    except (ValidationError, errors.ValidationError):
        pass
    finally:
        if inserted_rp is not None:
            await pool_repo.delete_resource_pool(admin_user, inserted_rp.id)


@given(rp=rp_strat())
@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@pytest.mark.asyncio
async def test_get_classes(rp: models.ResourcePool, app_config: Config, admin_user: base_models.APIUser):
    inserted_rp = None
    pool_repo = app_config.rp_repo
    try:
        inserted_rp = await create_rp(rp, pool_repo, api_user=admin_user)
        assert inserted_rp.id is not None
        retrieved_classes = await pool_repo.get_classes(resource_pool_id=inserted_rp.id, api_user=admin_user)
        assert all(c in inserted_rp.classes for c in retrieved_classes)
    except (ValidationError, errors.ValidationError):
        pass
    finally:
        if inserted_rp is not None:
            await pool_repo.delete_resource_pool(admin_user, inserted_rp.id)


@given(rp=rp_strat())
@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@pytest.mark.asyncio
async def test_get_class_by_id(rp: models.ResourcePool, app_config: Config, admin_user: base_models.APIUser):
    inserted_rp = None
    pool_repo = app_config.rp_repo
    try:
        inserted_rp = await create_rp(rp, pool_repo, api_user=admin_user)
        assert inserted_rp.id is not None
        a_class = inserted_rp.classes.copy().pop()
        assert a_class.id is not None
        retrieved_classes = await pool_repo.get_classes(id=a_class.id, api_user=admin_user)
        assert len(retrieved_classes) == 1
        assert retrieved_classes[0] == a_class
    except (ValidationError, errors.ValidationError):
        pass
    finally:
        if inserted_rp is not None:
            await pool_repo.delete_resource_pool(admin_user, inserted_rp.id)


@given(rp=rp_strat())
@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@pytest.mark.asyncio
async def test_get_class_by_name(rp: models.ResourcePool, app_config: Config, admin_user: base_models.APIUser):
    inserted_rp = None
    pool_repo = app_config.rp_repo
    try:
        inserted_rp = await create_rp(rp, pool_repo, api_user=admin_user)
        assert inserted_rp.id is not None
        a_class = inserted_rp.classes.copy().pop()
        assert a_class.id is not None
        retrieved_classes = await pool_repo.get_classes(name=a_class.name, api_user=admin_user)
        assert len(retrieved_classes) >= 1
        assert any([a_class == cls for cls in retrieved_classes])
    except (ValidationError, errors.ValidationError):
        pass
    finally:
        if inserted_rp is not None:
            await pool_repo.delete_resource_pool(admin_user, inserted_rp.id)


@given(rp=rp_strat())
@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@pytest.mark.asyncio
async def test_resource_pool_delete(rp: models.ResourcePool, app_config: Config, admin_user: base_models.APIUser):
    pool_repo = app_config.rp_repo
    try:
        inserted_rp = await create_rp(rp, pool_repo, api_user=admin_user)
        assert inserted_rp.id is not None
        await pool_repo.delete_resource_pool(id=inserted_rp.id, api_user=admin_user)
        retrieved_rps = await pool_repo.get_resource_pools(id=inserted_rp.id, api_user=admin_user)
        assert len(retrieved_rps) == 0
    except (ValidationError, errors.ValidationError):
        pass


@given(rc=rc_non_default_strat(), rp=rp_strat())
@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@pytest.mark.asyncio
async def test_resource_class_create(
    rc: models.ResourceClass,
    rp: models.ResourcePool,
    app_config: Config,
    admin_user: base_models.APIUser,
):
    inserted_rp = None
    pool_repo = app_config.rp_repo
    try:
        inserted_rp = await create_rp(rp, pool_repo, api_user=admin_user)
        assert inserted_rp.id is not None
        inserted_class = await pool_repo.insert_resource_class(
            resource_class=rc, resource_pool_id=inserted_rp.id, api_user=admin_user
        )

        assert inserted_class is not None
        retrieved_rps = await pool_repo.get_resource_pools(id=inserted_rp.id, api_user=admin_user)
        assert len(retrieved_rps) == 1
        retrieved_rp = retrieved_rps[0]
        assert len(retrieved_rp.classes) >= 1
        assert (
            sum([i == inserted_class for i in retrieved_rp.classes]) == 1
        ), f"class {inserted_class} should be in {retrieved_rp.classes}"
    except (ValidationError, errors.ValidationError):
        pass
    finally:
        if inserted_rp is not None:
            await pool_repo.delete_resource_pool(admin_user, inserted_rp.id)


@given(rp=rp_strat())
@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@pytest.mark.asyncio
async def test_resource_class_delete(rp: models.ResourcePool, app_config: Config, admin_user: base_models.APIUser):
    inserted_rp = None
    pool_repo = app_config.rp_repo
    try:
        inserted_rp = await create_rp(rp, pool_repo, api_user=admin_user)
        assert inserted_rp.id is not None
        assert len(inserted_rp.classes) > 0
        non_default_rc = [cls for cls in inserted_rp.classes if not cls.default]
        assert len(non_default_rc) > 0
        removed_cls = non_default_rc[0]
        assert removed_cls.id is not None
        await pool_repo.delete_resource_class(
            resource_pool_id=inserted_rp.id, resource_class_id=removed_cls.id, api_user=admin_user
        )

        retrieved_rps = await pool_repo.get_resource_pools(id=inserted_rp.id, api_user=admin_user)
        assert len(retrieved_rps) == 1
        retrieved_rp = retrieved_rps[0]
        assert not any(
            [i == removed_cls for i in retrieved_rp.classes]
        ), f"class {removed_cls} should not be in {retrieved_rp.classes}"
    except (ValidationError, errors.ValidationError):
        pass
    finally:
        if inserted_rp is not None:
            await pool_repo.delete_resource_pool(admin_user, inserted_rp.id)


@given(rp=rp_strat(), rc_update=rc_update_reqs_dict)
@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@pytest.mark.asyncio
async def test_resource_class_update(
    rp: models.ResourcePool, app_config: Config, admin_user: base_models.APIUser, rc_update: dict
):
    inserted_rp = None
    pool_repo = app_config.rp_repo
    try:
        inserted_rp = await pool_repo.insert_resource_pool(resource_pool=rp, api_user=admin_user)
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
        updated_rc = await pool_repo.update_resource_class(
            resource_pool_id=inserted_rp.id,
            resource_class_id=rc_to_update.id,
            put=False,
            api_user=admin_user,
            **new_rc_dict,
        )

        retrieved_rps = await pool_repo.get_resource_pools(id=inserted_rp.id, api_user=admin_user)
        assert len(retrieved_rps) == 1
        retrieved_rp = retrieved_rps[0]
        assert updated_rc.id == rc_to_update.id
        assert (
            sum([i == updated_rc for i in retrieved_rp.classes]) == 1
        ), f"class {updated_rc} should be in {retrieved_rp.classes}"
        assert not any(
            [i == rc_to_update for i in retrieved_rp.classes]
        ), f"class {rc_to_update} should not be in {retrieved_rp.classes}"
    except (ValidationError, errors.ValidationError):
        pass
    finally:
        if inserted_rp is not None:
            await pool_repo.delete_resource_pool(admin_user, inserted_rp.id)


@given(rp=rp_strat())
@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@pytest.mark.asyncio
async def test_lookup_rp_by_name(rp: models.ResourcePool, app_config: Config, admin_user: base_models.APIUser):
    inserted_rp = None
    pool_repo = app_config.rp_repo
    try:
        inserted_rp = await create_rp(rp, pool_repo, api_user=admin_user)
        assert inserted_rp.id is not None
        retrieved_rps = await pool_repo.get_resource_pools(name=inserted_rp.name, api_user=admin_user)
        assert len(retrieved_rps) >= 1
        assert any([rp == inserted_rp for rp in retrieved_rps])
    except (ValidationError, errors.ValidationError):
        pass
    finally:
        if inserted_rp is not None:
            await pool_repo.delete_resource_pool(admin_user, inserted_rp.id)


@given(rc=rc_non_default_strat())
@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@pytest.mark.asyncio
async def test_insert_class_in_nonexisting_rp(
    app_config: Config, rc: models.ResourceClass, admin_user: base_models.APIUser
):
    with pytest.raises(errors.MissingResourceError):
        await app_config.rp_repo.insert_resource_class(resource_class=rc, resource_pool_id=99999, api_user=admin_user)


@given(new_quota_id=a_uuid_string)
@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@pytest.mark.asyncio
async def test_update_quota_in_nonexisting_rp(app_config: Config, new_quota_id: str, admin_user: base_models.APIUser):
    with pytest.raises(errors.MissingResourceError):
        await app_config.rp_repo.update_resource_pool(id=99999, api_user=admin_user, quota=new_quota_id)


@given(public_rp=public_rp_strat, private_rp=private_rp_strat)
@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@pytest.mark.asyncio
async def test_resource_pools_access_control(
    public_rp: models.ResourcePool,
    private_rp: models.ResourcePool,
    admin_user: base_models.APIUser,
    loggedin_user: base_models.APIUser,
    app_config: Config,
):
    inserted_public_rp = None
    inserted_private_rp = None
    pool_repo = app_config.rp_repo
    user_repo = app_config.user_repo
    try:
        inserted_public_rp = await create_rp(public_rp, pool_repo, admin_user)
        assert inserted_public_rp.id is not None
        inserted_private_rp = await create_rp(private_rp, pool_repo, admin_user)
        assert inserted_public_rp.id is not None
        admin_rps = await pool_repo.get_resource_pools(admin_user)
        loggedin_user_rps = await pool_repo.get_resource_pools(loggedin_user)
        assert inserted_public_rp in loggedin_user_rps
        assert inserted_public_rp in admin_rps
        assert inserted_private_rp not in loggedin_user_rps
        assert inserted_private_rp in admin_rps
        assert loggedin_user.id is not None
        user_to_add = base_models.User(keycloak_id=loggedin_user.id)
        updated_users = await user_repo.update_resource_pool_users(
            admin_user, inserted_private_rp.id, [loggedin_user.id], append=True
        )

        assert user_to_add in [remove_id_from_user(user) for user in updated_users]
        loggedin_user_rps = await pool_repo.get_resource_pools(loggedin_user)
        assert inserted_private_rp in loggedin_user_rps
    except (ValidationError, errors.ValidationError):
        pass
    finally:
        if inserted_public_rp is not None:
            await pool_repo.delete_resource_pool(admin_user, inserted_public_rp.id)
        if inserted_private_rp is not None:
            await pool_repo.delete_resource_pool(admin_user, inserted_private_rp.id)


@given(rp1=rp_strat(), rp2=rp_strat())
@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@pytest.mark.asyncio
async def test_classes_filtering(
    rp1: models.ResourcePool,
    rp2: models.ResourcePool,
    admin_user: base_models.APIUser,
    app_config: Config,
):
    inserted_rp1 = None
    inserted_rp2 = None
    pool_repo = app_config.rp_repo
    try:
        inserted_rp1 = await create_rp(rp1, pool_repo, api_user=admin_user)
        inserted_rp2 = await create_rp(rp2, pool_repo, api_user=admin_user)
        assert inserted_rp1.id is not None
        assert inserted_rp2.id is not None
        all_rps = await pool_repo.get_resource_pools(admin_user)
        assert len(all_rps) == 2
        assert len(all_rps[0].classes) + len(all_rps[1].classes) == len(inserted_rp1.classes) + len(
            inserted_rp2.classes
        )
        cpu_filter = 1
        memory_filter = 4
        filtered_resource_pools = await pool_repo.filter_resource_pools(
            admin_user, cpu=cpu_filter, memory=memory_filter
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

    except (ValidationError, errors.ValidationError):
        pass
    finally:
        if inserted_rp1 is not None:
            await pool_repo.delete_resource_pool(admin_user, inserted_rp1.id)
        if inserted_rp2 is not None:
            await pool_repo.delete_resource_pool(admin_user, inserted_rp2.id)
