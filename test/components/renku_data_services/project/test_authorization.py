import pytest
from ulid import ULID

from renku_data_services.base_models import APIUser
from renku_data_services.data_api.config import Config
from renku_data_services.errors import errors
from renku_data_services.authz.models import AccessLevel, PermissionQualifier


admin_user = APIUser(is_admin=True, id="some-id", access_token="some-token", name="admin")  # nosec B106
anon_user = APIUser(is_admin=False)
regular_user1 = APIUser(is_admin=False, id="some-id1", access_token="some-token1", name="some-user1")  # nosec B106
regular_user2 = APIUser(is_admin=False, id="some-id2", access_token="some-token2", name="some-user2")  # nosec B106


@pytest.mark.asyncio
@pytest.mark.parametrize("public_project", [True, False])
async def test_adding_project(app_config: Config, public_project: bool):
    authz = app_config.project_authz
    project_id = str(ULID())
    await authz.create_project(requested_by=regular_user1, project_id=project_id, public_project=public_project)
    assert await authz.has_permission(regular_user1, project_id, AccessLevel.OWNER)
    assert await authz.has_permission(admin_user, project_id, AccessLevel.OWNER)
    assert public_project == await authz.has_permission(anon_user, project_id, AccessLevel.PUBLIC_ACCESS)
    assert public_project == await authz.has_permission(regular_user2, project_id, AccessLevel.PUBLIC_ACCESS)
    assert not await authz.has_permission(anon_user, project_id, AccessLevel.MEMBER)
    assert not await authz.has_permission(regular_user2, project_id, AccessLevel.MEMBER)


@pytest.mark.asyncio
@pytest.mark.parametrize("public_project", [True, False])
async def test_granting_access(app_config: Config, public_project: bool):
    authz = app_config.project_authz
    project_id = str(ULID())
    await authz.create_project(requested_by=regular_user1, project_id=project_id, public_project=public_project)
    assert await authz.has_permission(regular_user1, project_id, AccessLevel.OWNER)
    assert public_project == await authz.has_permission(regular_user2, project_id, AccessLevel.PUBLIC_ACCESS)
    assert public_project == await authz.has_permission(anon_user, project_id, AccessLevel.PUBLIC_ACCESS)
    await authz.grant_permission(
        requested_by=regular_user1, user_id=regular_user2.id, project_id=project_id, access_level=AccessLevel.MEMBER
    )
    assert await authz.has_permission(regular_user2, project_id, AccessLevel.MEMBER)
    assert not await authz.has_permission(anon_user, project_id, AccessLevel.MEMBER)


@pytest.mark.asyncio
@pytest.mark.parametrize("public_project", [True, False])
async def test_listing_users_with_access(app_config: Config, public_project: bool):
    authz = app_config.project_authz
    project_id = str(ULID())
    await authz.create_project(requested_by=regular_user1, project_id=project_id, public_project=public_project)
    access_qualifier, user_list = await authz.project_accessible_by(
        regular_user1, project_id, AccessLevel.PUBLIC_ACCESS
    )
    if public_project:
        assert access_qualifier == PermissionQualifier.ALL
        assert user_list == []
    else:
        assert access_qualifier == PermissionQualifier.SOME
        assert user_list == [regular_user1.id]


@pytest.mark.asyncio
async def test_listing_projects_with_access(app_config: Config):
    authz = app_config.project_authz
    public_project_id = str(ULID())
    private_project_id1 = str(ULID())
    private_project_id2 = str(ULID())
    await authz.create_project(requested_by=regular_user1, project_id=public_project_id, public_project=True)
    await authz.create_project(requested_by=regular_user1, project_id=private_project_id1, public_project=False)
    await authz.create_project(requested_by=regular_user1, project_id=private_project_id2, public_project=False)
    assert set([public_project_id, private_project_id1, private_project_id2]) == set(
        await authz.user_can_access(regular_user1, regular_user1.id, AccessLevel.OWNER)
    )
    assert set([public_project_id, private_project_id1, private_project_id2]) == set(
        await authz.user_can_access(regular_user1, regular_user1.id, AccessLevel.MEMBER)
    )
    assert set([public_project_id, private_project_id1, private_project_id2]) == set(
        await authz.user_can_access(regular_user1, regular_user1.id, AccessLevel.PUBLIC_ACCESS)
    )
    assert set([public_project_id, private_project_id1, private_project_id2]) == set(
        await authz.user_can_access(admin_user, admin_user.id, AccessLevel.OWNER)
    )
    assert set([public_project_id, private_project_id1, private_project_id2]) == set(
        await authz.user_can_access(admin_user, regular_user1.id, AccessLevel.OWNER)
    )
    with pytest.raises(errors.Unauthorized):
        await authz.user_can_access(anon_user, regular_user1.id, AccessLevel.PUBLIC_ACCESS)
        await authz.user_can_access(regular_user2, regular_user1.id, AccessLevel.PUBLIC_ACCESS)
    assert set([public_project_id]) == set(
        await authz.user_can_access(anon_user, PermissionQualifier.ALL, AccessLevel.PUBLIC_ACCESS)
    )
    assert set([public_project_id]) == set(
        await authz.user_can_access(regular_user2, regular_user2.id, AccessLevel.PUBLIC_ACCESS)
    )
    await authz.grant_permission(regular_user1, regular_user2.id, private_project_id1, AccessLevel.MEMBER)
    assert set([public_project_id, private_project_id1]) == set(
        await authz.user_can_access(regular_user2, regular_user2.id, AccessLevel.PUBLIC_ACCESS)
    )
    assert set([private_project_id1]) == set(
        await authz.user_can_access(regular_user2, regular_user2.id, AccessLevel.MEMBER)
    )
    assert set() == set(await authz.user_can_access(regular_user2, regular_user2.id, AccessLevel.OWNER))
    # Test project deletion
    await authz.delete_project(regular_user1, private_project_id1)
    assert private_project_id1 not in set(
        await authz.user_can_access(regular_user1, regular_user1.id, AccessLevel.OWNER)
    )
    assert private_project_id1 not in set(await authz.user_can_access(admin_user, admin_user.id, AccessLevel.OWNER))
