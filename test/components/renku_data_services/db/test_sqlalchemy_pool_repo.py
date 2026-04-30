from dataclasses import asdict
from unittest.mock import AsyncMock

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.authz.models import Visibility
from renku_data_services.base_models import APIUser
from renku_data_services.crc import models
from renku_data_services.crc.models import MemberType, ResourcePoolMemberIdentifier
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.namespace import models as namespace_models
from renku_data_services.project import models as project_models
from test.components.renku_data_services.crc_models.hypothesis import (
    a_name,
    a_uuid_string,
    private_rp_strat,
    public_rp_strat,
    rc_non_default_strat,
    rc_update_reqs_dict,
    rp_strat,
)
from test.utils import KindCluster, create_rp, remove_id_from_user, sort_rp_classes


@given(rp=rp_strat())
@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")
async def test_resource_pool_insert_get(
    rp: models.UnsavedResourcePool,
    app_manager_instance: DependencyManager,
    admin_user: base_models.APIUser,
    cluster: KindCluster,
) -> None:
    run_migrations_for_app("common")
    inserted_rp = None
    pool_repo = app_manager_instance.rp_repo
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
@pytest.mark.xdist_group("sessions")
async def test_resource_pool_update_name(
    rp: models.UnsavedResourcePool,
    app_manager_instance: DependencyManager,
    new_name: str,
    admin_user: base_models.APIUser,
    cluster: KindCluster,
) -> None:
    run_migrations_for_app("common")
    inserted_rp = None
    pool_repo = app_manager_instance.rp_repo
    try:
        inserted_rp = await create_rp(rp, pool_repo, api_user=admin_user)
        assert inserted_rp.id is not None
        updated_rp = await pool_repo.update_resource_pool(
            api_user=admin_user, resource_pool_id=inserted_rp.id, update=models.ResourcePoolPatch(name=new_name)
        )
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
@pytest.mark.xdist_group("sessions")
async def test_resource_pool_update_quota(
    rp: models.UnsavedResourcePool,
    app_manager_instance: DependencyManager,
    admin_user: base_models.APIUser,
    cluster: KindCluster,
) -> None:
    run_migrations_for_app("common")
    pool_repo = app_manager_instance.rp_repo
    try:
        inserted_rp = await create_rp(rp, pool_repo, api_user=admin_user)
        assert inserted_rp.id is not None
        assert inserted_rp.quota is not None
        updated_rp = await pool_repo.update_resource_pool(
            api_user=admin_user,
            resource_pool_id=inserted_rp.id,
            update=models.ResourcePoolPatch(quota=models.QuotaPatch(cpu=999, memory=999, gpu=999)),
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
@pytest.mark.xdist_group("sessions")
async def test_resource_pool_update_classes(
    rp: models.UnsavedResourcePool,
    app_manager_instance: DependencyManager,
    data,
    admin_user: base_models.APIUser,
    cluster: KindCluster,
) -> None:
    run_migrations_for_app("common")
    inserted_rp = None
    pool_repo = app_manager_instance.rp_repo
    try:
        inserted_rp = await create_rp(rp, pool_repo, api_user=admin_user)
        assert inserted_rp.id is not None
        rc_update_reqs = [{"id": rc.id, **data.draw(rc_update_reqs_dict)} for rc in inserted_rp.classes]
        classes_update = [
            models.ResourceClassPatchWithId(
                id=rc["id"],
                cpu=rc.get("cpu"),
                gpu=rc.get("gpu"),
                memory=rc.get("memory"),
                max_storage=rc.get("max_storage"),
            )
            for rc in rc_update_reqs
        ]
        expected_updated_classes = [
            models.ResourceClass(**{**asdict(rc), **rc_update, "node_affinities": rc.node_affinities})
            for rc, rc_update in zip(inserted_rp.classes, rc_update_reqs, strict=True)
        ]

        updated_rp = await pool_repo.update_resource_pool(
            api_user=admin_user,
            resource_pool_id=inserted_rp.id,
            update=models.ResourcePoolPatch(classes=classes_update),
        )

        assert updated_rp.id == inserted_rp.id
        assert len(updated_rp.classes) == len(inserted_rp.classes)
        assert sort_rp_classes(
            updated_rp.classes,
        ) == sort_rp_classes(
            expected_updated_classes,
        )
        retrieved_rps = await pool_repo.get_resource_pools(id=inserted_rp.id, api_user=admin_user)
        assert len(retrieved_rps) == 1
        retrieved_rp = retrieved_rps[0]
        assert updated_rp.id == retrieved_rp.id
        assert updated_rp.name == retrieved_rp.name
        assert updated_rp.idle_threshold == retrieved_rp.idle_threshold
        assert sort_rp_classes(updated_rp.classes) == sort_rp_classes(retrieved_rp.classes)
        assert updated_rp.quota == retrieved_rp.quota
    except (ValidationError, errors.ValidationError):
        pass
    finally:
        if inserted_rp is not None:
            await pool_repo.delete_resource_pool(admin_user, inserted_rp.id)


@given(rp=rp_strat())
@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")
async def test_get_classes(
    rp: models.UnsavedResourcePool,
    app_manager_instance: DependencyManager,
    admin_user: base_models.APIUser,
    cluster: KindCluster,
) -> None:
    run_migrations_for_app("common")
    inserted_rp = None
    pool_repo = app_manager_instance.rp_repo
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
@pytest.mark.xdist_group("sessions")
async def test_get_class_by_id(
    rp: models.UnsavedResourcePool,
    app_manager_instance: DependencyManager,
    admin_user: base_models.APIUser,
    cluster: KindCluster,
) -> None:
    run_migrations_for_app("common")
    inserted_rp = None
    pool_repo = app_manager_instance.rp_repo
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
@pytest.mark.xdist_group("sessions")
async def test_get_class_by_name(
    rp: models.UnsavedResourcePool,
    app_manager_instance: DependencyManager,
    admin_user: base_models.APIUser,
    cluster: KindCluster,
) -> None:
    run_migrations_for_app("common")
    inserted_rp = None
    pool_repo = app_manager_instance.rp_repo
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
@pytest.mark.xdist_group("sessions")
async def test_resource_pool_delete(
    rp: models.UnsavedResourcePool,
    app_manager_instance: DependencyManager,
    admin_user: base_models.APIUser,
    cluster: KindCluster,
) -> None:
    run_migrations_for_app("common")
    pool_repo = app_manager_instance.rp_repo
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
@pytest.mark.xdist_group("sessions")
async def test_resource_class_create(
    rc: models.UnsavedResourceClass,
    rp: models.UnsavedResourcePool,
    app_manager_instance: DependencyManager,
    admin_user: base_models.APIUser,
    cluster: KindCluster,
) -> None:
    run_migrations_for_app("common")
    inserted_rp = None
    pool_repo = app_manager_instance.rp_repo
    try:
        inserted_rp = await create_rp(rp, pool_repo, api_user=admin_user)
        assert inserted_rp.id is not None
        inserted_class = await pool_repo.insert_resource_class(
            api_user=admin_user,
            resource_pool_id=inserted_rp.id,
            new_resource_class=rc,
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
@pytest.mark.xdist_group("sessions")
async def test_resource_class_delete(
    rp: models.UnsavedResourcePool,
    app_manager_instance: DependencyManager,
    admin_user: base_models.APIUser,
    cluster: KindCluster,
) -> None:
    run_migrations_for_app("common")
    inserted_rp = None
    pool_repo = app_manager_instance.rp_repo
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
@pytest.mark.xdist_group("sessions")
async def test_resource_class_update(
    rp: models.UnsavedResourcePool,
    app_manager_instance: DependencyManager,
    admin_user: base_models.APIUser,
    rc_update: dict,
    cluster: KindCluster,
) -> None:
    run_migrations_for_app("common")
    inserted_rp = None
    pool_repo = app_manager_instance.rp_repo
    try:
        inserted_rp = await pool_repo.insert_resource_pool(new_resource_pool=rp, api_user=admin_user)
        assert inserted_rp is not None
        assert inserted_rp.id is not None
        assert len(inserted_rp.classes) > 0
        default_rcs = [cls for cls in inserted_rp.classes if cls.default]
        assert len(default_rcs) == 1
        rc_to_update = default_rcs[0]
        assert rc_to_update.id is not None
        updated_rc = await pool_repo.update_resource_class(
            api_user=admin_user,
            resource_pool_id=inserted_rp.id,
            resource_class_id=rc_to_update.id,
            update=models.ResourceClassPatch(**rc_update),
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
@pytest.mark.xdist_group("sessions")
async def test_lookup_rp_by_name(
    rp: models.UnsavedResourcePool,
    app_manager_instance: DependencyManager,
    admin_user: base_models.APIUser,
    cluster: KindCluster,
) -> None:
    run_migrations_for_app("common")
    inserted_rp = None
    pool_repo = app_manager_instance.rp_repo
    try:
        inserted_rp = await create_rp(rp, pool_repo, api_user=admin_user)
        assert inserted_rp.id is not None
        retrieved_rps = await pool_repo.get_resource_pools(name=inserted_rp.name, api_user=admin_user)
        assert len(retrieved_rps) >= 1
        assert any([rp.id == inserted_rp.id for rp in retrieved_rps])
    except (ValidationError, errors.ValidationError):
        pass
    finally:
        if inserted_rp is not None:
            await pool_repo.delete_resource_pool(admin_user, inserted_rp.id)


@given(rc=rc_non_default_strat())
@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")
async def test_insert_class_in_nonexisting_rp(
    app_manager_instance: DependencyManager,
    rc: models.ResourceClass,
    admin_user: base_models.APIUser,
    cluster: KindCluster,
) -> None:
    run_migrations_for_app("common")
    with pytest.raises(errors.MissingResourceError):
        await app_manager_instance.rp_repo.insert_resource_class(
            new_resource_class=rc, resource_pool_id=99999, api_user=admin_user
        )


@given(new_quota_id=a_uuid_string)
@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")
async def test_update_quota_in_nonexisting_rp(
    app_manager_instance: DependencyManager,
    new_quota_id: str,
    admin_user: base_models.APIUser,
    cluster: KindCluster,
) -> None:
    run_migrations_for_app("common")
    with pytest.raises(errors.MissingResourceError):
        await app_manager_instance.rp_repo.update_resource_pool(
            api_user=admin_user,
            resource_pool_id=99999,
            update=models.ResourcePoolPatch(quota=models.QuotaPatch(cpu=999, memory=999, gpu=999)),
        )


@given(public_rp=public_rp_strat, private_rp=private_rp_strat)
@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")
async def test_resource_pools_access_control(
    public_rp: models.UnsavedResourcePool,
    private_rp: models.UnsavedResourcePool,
    admin_user: base_models.APIUser,
    loggedin_user: base_models.APIUser,
    app_manager_instance: DependencyManager,
    cluster: KindCluster,
) -> None:
    run_migrations_for_app("common")
    inserted_public_rp = None
    inserted_private_rp = None
    pool_repo = app_manager_instance.rp_repo
    member_repo = app_manager_instance.member_repo
    try:
        inserted_public_rp = await create_rp(public_rp, pool_repo, admin_user)
        assert inserted_public_rp.id is not None
        inserted_private_rp = await create_rp(private_rp, pool_repo, admin_user)
        assert inserted_public_rp.id is not None
        admin_rps = await pool_repo.get_resource_pools(admin_user)
        loggedin_user_rps = await pool_repo.get_resource_pools(loggedin_user)
        assert any(inserted_public_rp.id == rp.id for rp in loggedin_user_rps)
        assert any(inserted_public_rp.id == rp.id for rp in admin_rps)
        assert all(inserted_private_rp.id != rp.id for rp in loggedin_user_rps)
        assert any(inserted_private_rp.id == rp.id for rp in admin_rps)
        assert loggedin_user.id is not None
        await app_manager_instance.kc_user_repo._add_api_user(loggedin_user)
        user_to_add = base_models.User(keycloak_id=loggedin_user.id)
        updated_members = await member_repo.update_resource_pool_users(
            admin_user, inserted_private_rp.id, [loggedin_user.id], append=True
        )

        assert user_to_add in [remove_id_from_user(user) for user in updated_members]
        loggedin_user_rps = await pool_repo.get_resource_pools(loggedin_user)
        assert any(inserted_private_rp.id == rp.id for rp in loggedin_user_rps)
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
@pytest.mark.xdist_group("sessions")
async def test_classes_filtering(
    rp1: models.ResourcePool,
    rp2: models.ResourcePool,
    admin_user: base_models.APIUser,
    app_manager_instance: DependencyManager,
    cluster: KindCluster,
) -> None:
    run_migrations_for_app("common")
    inserted_rp1 = None
    inserted_rp2 = None
    pool_repo = app_manager_instance.rp_repo
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


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")
async def test_member_repository_polymorphic_membership(
    app_manager_instance: DependencyManager,
    admin_user: base_models.APIUser,
) -> None:
    run_migrations_for_app("common")

    # Mock quotas_repo to avoid K8s client errors
    mock_quotas_repo = AsyncMock()
    mock_quota = models.Quota(cpu=10.0, memory=100, gpu=0, id="mock-quota-id")

    # Configure async methods
    mock_quotas_repo.create_quota = AsyncMock(return_value=mock_quota)
    mock_quotas_repo.get_quota = AsyncMock(return_value=mock_quota)

    app_manager_instance.quotas_repo = mock_quotas_repo
    app_manager_instance.rp_repo.quotas_repo = mock_quotas_repo

    # Ensure admin user exists in the database
    await app_manager_instance.kc_user_repo._add_api_user(admin_user)

    member_repo = app_manager_instance.member_repo

    pool_repo = app_manager_instance.rp_repo
    group_repo = app_manager_instance.group_repo
    project_repo = app_manager_instance.project_repo

    # Create a resource pool
    rp = models.UnsavedResourcePool(
        name="test-poly-pool",
        classes=[],
        quota=models.UnsavedQuota(cpu=10.0, memory=100, gpu=0),
        public=False,
        default=False,
        platform=models.RuntimePlatform.linux_amd64,
    )
    inserted_rp = await create_rp(rp, pool_repo, admin_user)

    rp_id = inserted_rp.id

    # 1. Test User membership
    user_id = "user-123"
    # Ensure user exists in the database
    await app_manager_instance.kc_user_repo._add_api_user(APIUser(id=user_id, full_name="Test User"))
    member = models.ResourcePoolMemberIdentifier(member_type=models.MemberType.USER, member_id=user_id)
    await member_repo.grant_resource_pool_members(admin_user, rp_id, [member])

    # 2. Test Group membership
    group_slug = "group-456"
    member_group = ResourcePoolMemberIdentifier(member_type=MemberType.GROUP, member_id=group_slug)
    with pytest.raises(errors.MissingResourceError):
        await member_repo.grant_resource_pool_members(admin_user, rp_id, [member_group])

    await group_repo.insert_group(admin_user, namespace_models.UnsavedGroup(slug=group_slug, name="Test Group"))

    group_member = models.ResourcePoolMemberIdentifier(member_type=models.MemberType.GROUP, member_id=group_slug)
    await member_repo.grant_resource_pool_members(admin_user, rp_id, [group_member])

    # 3. Test Project membership (addressed as "<namespace-slug>/<project-slug>")
    await project_repo.insert_project(
        admin_user,
        project_models.UnsavedProject(
            name="Test Project",
            slug="test-proj",
            namespace=group_slug,
            visibility=Visibility.PUBLIC,
            created_by=admin_user.id,
        ),
    )

    project_path = f"{group_slug}/test-proj"
    project_member = ResourcePoolMemberIdentifier(member_type=MemberType.PROJECT, member_id=project_path)
    await member_repo.grant_resource_pool_members(admin_user, rp_id, [project_member])

    # 4. Test failure for non-existent group
    with pytest.raises(errors.MissingResourceError):
        bad_group = models.ResourcePoolMemberIdentifier(
            member_type=models.MemberType.GROUP, member_id="non-existent-group"
        )
        await member_repo.grant_resource_pool_members(admin_user, rp_id, [bad_group])

    # 5. Test failure for non-existent project
    # 5a. Non-existent project (well-formed path, but not in DB)
    with pytest.raises(errors.MissingResourceError):
        await member_repo.grant_resource_pool_members(
            admin_user,
            rp_id,
            [
                ResourcePoolMemberIdentifier(
                    member_type=MemberType.PROJECT,
                    member_id=f"{group_slug}/does-not-exist",
                )
            ],
        )

    # 5b. Malformed project identifier (ULID, bare slug, empty segment) rejected at construction.
    for bad in (str(ULID()), "just-a-slug", "ns/", "/proj", "ns//proj"):
        with pytest.raises(errors.ValidationError):
            ResourcePoolMemberIdentifier(member_type=MemberType.PROJECT, member_id=bad)

    # 5c. Malformed group identifier rejected at construction.
    with pytest.raises(errors.ValidationError):
        ResourcePoolMemberIdentifier(member_type=MemberType.GROUP, member_id="not a slug!")


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")
async def test_member_repository_revoke_membership(
    app_manager_instance: DependencyManager,
    admin_user: base_models.APIUser,
    cluster: KindCluster,
) -> None:
    run_migrations_for_app("common")
    member_repo = app_manager_instance.member_repo
    pool_repo = app_manager_instance.rp_repo

    # Create a resource pool
    rp = models.UnsavedResourcePool(
        name="test-revoke-pool",
        classes=[],
        quota=models.UnsavedQuota(cpu=10.0, memory=100, gpu=0),
        public=False,
        default=False,
        platform=models.RuntimePlatform.linux_amd64,
    )
    inserted_rp = await create_rp(rp, pool_repo, admin_user)
    rp_id = inserted_rp.id

    user_id = "user-revoke"
    # Ensure user exists in the database
    await app_manager_instance.kc_user_repo._add_api_user(APIUser(id=user_id, full_name="Revoke User"))
    member_user = ResourcePoolMemberIdentifier(member_type=MemberType.USER, member_id=user_id)

    # Grant
    await member_repo.grant_resource_pool_members(admin_user, rp_id, [member_user])

    # Revoke
    await member_repo.revoke_resource_pool_members(admin_user, rp_id, [member_user])


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")
async def test_member_repository_rejects_unknown_user(
    app_manager_instance: DependencyManager,
    admin_user: base_models.APIUser,
) -> None:
    run_migrations_for_app("common")

    mock_quotas_repo = AsyncMock()
    mock_quota = models.Quota(cpu=10.0, memory=100, gpu=0, id="mock-quota-id")
    mock_quotas_repo.create_quota = AsyncMock(return_value=mock_quota)
    mock_quotas_repo.get_quota = AsyncMock(return_value=mock_quota)
    app_manager_instance.quotas_repo = mock_quotas_repo
    app_manager_instance.rp_repo.quotas_repo = mock_quotas_repo

    await app_manager_instance.kc_user_repo._add_api_user(admin_user)

    member_repo = app_manager_instance.member_repo
    pool_repo = app_manager_instance.rp_repo

    rp = models.UnsavedResourcePool(
        name="test-user-validation-pool",
        classes=[],
        quota=models.UnsavedQuota(cpu=10.0, memory=100, gpu=0),
        public=False,
        default=False,
        platform=models.RuntimePlatform.linux_amd64,
    )
    inserted_rp = await create_rp(rp, pool_repo, admin_user)

    # Empty id -> ValidationError
    with pytest.raises(errors.ValidationError):
        await member_repo.grant_resource_pool_members(
            admin_user,
            inserted_rp.id,
            [ResourcePoolMemberIdentifier(member_type=MemberType.USER, member_id="")],
        )

    # Unknown keycloak id -> MissingResourceError
    with pytest.raises(errors.MissingResourceError):
        await member_repo.grant_resource_pool_members(
            admin_user,
            inserted_rp.id,
            [ResourcePoolMemberIdentifier(member_type=MemberType.USER, member_id="does-not-exist")],
        )


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")
async def test_member_repository_rejects_bad_project_id(
    app_manager_instance: DependencyManager,
    admin_user: base_models.APIUser,
) -> None:
    run_migrations_for_app("common")

    mock_quotas_repo = AsyncMock()
    mock_quota = models.Quota(cpu=10.0, memory=100, gpu=0, id="mock-quota-id")
    mock_quotas_repo.create_quota = AsyncMock(return_value=mock_quota)
    mock_quotas_repo.get_quota = AsyncMock(return_value=mock_quota)
    app_manager_instance.quotas_repo = mock_quotas_repo
    app_manager_instance.rp_repo.quotas_repo = mock_quotas_repo

    await app_manager_instance.kc_user_repo._add_api_user(admin_user)

    member_repo = app_manager_instance.member_repo
    pool_repo = app_manager_instance.rp_repo

    rp = models.UnsavedResourcePool(
        name="test-bad-project-id-pool",
        classes=[],
        quota=models.UnsavedQuota(cpu=10.0, memory=100, gpu=0),
        public=False,
        default=False,
        platform=models.RuntimePlatform.linux_amd64,
    )
    inserted_rp = await create_rp(rp, pool_repo, admin_user)

    # Malformed ULID -> ValidationError
    with pytest.raises(errors.ValidationError):
        await member_repo.grant_resource_pool_members(
            admin_user,
            inserted_rp.id,
            [ResourcePoolMemberIdentifier(member_type=MemberType.PROJECT, member_id="not-a-ulid")],
        )


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")
async def test_member_repository_accepts_group_by_either_identifier(
    app_manager_instance: DependencyManager,
    admin_user: base_models.APIUser,
) -> None:
    run_migrations_for_app("common")

    mock_quotas_repo = AsyncMock()
    mock_quota = models.Quota(cpu=10.0, memory=100, gpu=0, id="mock-quota-id")
    mock_quotas_repo.create_quota = AsyncMock(return_value=mock_quota)
    mock_quotas_repo.get_quota = AsyncMock(return_value=mock_quota)
    app_manager_instance.quotas_repo = mock_quotas_repo
    app_manager_instance.rp_repo.quotas_repo = mock_quotas_repo

    await app_manager_instance.kc_user_repo._add_api_user(admin_user)

    member_repo = app_manager_instance.member_repo
    pool_repo = app_manager_instance.rp_repo
    group_repo = app_manager_instance.group_repo

    rp = models.UnsavedResourcePool(
        name="test-group-ident-pool",
        classes=[],
        quota=models.UnsavedQuota(cpu=10.0, memory=100, gpu=0),
        public=False,
        default=False,
        platform=models.RuntimePlatform.linux_amd64,
    )
    inserted_rp = await create_rp(rp, pool_repo, admin_user)

    group_slug = "group-ident"
    await group_repo.insert_group(
        admin_user,
        namespace_models.UnsavedGroup(slug=group_slug, name="Ident Group"),
    )

    ident = group_slug
    await member_repo.grant_resource_pool_members(
        admin_user,
        inserted_rp.id,
        [ResourcePoolMemberIdentifier(member_type=MemberType.GROUP, member_id=ident)],
    )
