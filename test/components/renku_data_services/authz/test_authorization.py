import pytest
from ulid import ULID

from renku_data_services.authz.models import MemberQualifier, Role, Scope
from renku_data_services.base_models import APIUser
from renku_data_services.app_config import Config
from renku_data_services.errors import errors

admin_user = APIUser(is_admin=True, id="some-id", access_token="some-token", name="admin")  # nosec B106
anon_user = APIUser(is_admin=False)
regular_user1 = APIUser(is_admin=False, id="some-id1", access_token="some-token1", name="some-user1")  # nosec B106
regular_user2 = APIUser(is_admin=False, id="some-id2", access_token="some-token2", name="some-user2")  # nosec B106


@pytest.mark.asyncio
@pytest.mark.parametrize("public_project", [True, False])
async def test_adding_deleting_project(app_config: Config, public_project: bool):
    authz = app_config.project_authz
    project_id = str(ULID())
    await authz.create_project(requested_by=regular_user1, project_id=project_id, public_project=public_project)
    assert await authz.has_permission(regular_user1, project_id, Scope.DELETE)
    assert await authz.has_permission(regular_user1, project_id, Scope.WRITE)
    assert await authz.has_permission(regular_user1, project_id, Scope.READ)
    assert await authz.has_permission(admin_user, project_id, Scope.DELETE)
    assert await authz.has_permission(admin_user, project_id, Scope.WRITE)
    assert await authz.has_permission(admin_user, project_id, Scope.READ)
    assert public_project == await authz.has_permission(anon_user, project_id, Scope.READ)
    assert public_project == await authz.has_permission(regular_user2, project_id, Scope.READ)
    assert not await authz.has_permission(anon_user, project_id, Scope.WRITE)
    assert not await authz.has_permission(regular_user2, project_id, Scope.WRITE)
    await authz.delete_project(regular_user1, project_id)
    assert not await authz.has_permission(admin_user, project_id, Scope.READ)
    assert not await authz.has_permission(admin_user, project_id, Scope.WRITE)
    assert not await authz.has_permission(admin_user, project_id, Scope.DELETE)
    assert not await authz.has_permission(regular_user1, project_id, Scope.READ)
    assert not await authz.has_permission(regular_user1, project_id, Scope.WRITE)
    assert not await authz.has_permission(regular_user1, project_id, Scope.DELETE)
    assert not await authz.has_permission(regular_user2, project_id, Scope.READ)
    assert not await authz.has_permission(regular_user2, project_id, Scope.WRITE)
    assert not await authz.has_permission(regular_user2, project_id, Scope.DELETE)


@pytest.mark.asyncio
@pytest.mark.parametrize("public_project", [True, False])
async def test_granting_access(app_config: Config, public_project: bool):
    authz = app_config.project_authz
    project_id = str(ULID())
    await authz.create_project(requested_by=regular_user1, project_id=project_id, public_project=public_project)
    assert await authz.has_role(regular_user1, project_id, Role.OWNER)
    assert public_project == await authz.has_permission(regular_user2, project_id, Scope.READ)
    assert public_project == await authz.has_permission(anon_user, project_id, Scope.READ)
    await authz.add_user(requested_by=regular_user1, user_id=regular_user2.id, project_id=project_id, role=Role.MEMBER)
    assert await authz.has_role(regular_user2, project_id, Role.MEMBER)
    assert await authz.has_permission(regular_user2, project_id, Scope.READ)
    assert not await authz.has_permission(regular_user2, project_id, Scope.WRITE)
    assert not await authz.has_permission(regular_user2, project_id, Scope.DELETE)
    assert public_project == await authz.has_role(anon_user, project_id, Role.MEMBER)


@pytest.mark.asyncio
@pytest.mark.parametrize("public_project", [True, False])
async def test_listing_users_with_access(app_config: Config, public_project: bool):
    authz = app_config.project_authz
    project_id = str(ULID())
    await authz.create_project(requested_by=regular_user1, project_id=project_id, public_project=public_project)
    access_qualifier, user_list = await authz.get_project_users(regular_user1, project_id, Role.MEMBER)
    if public_project:
        assert access_qualifier == MemberQualifier.ALL
        assert user_list == []
    else:
        assert access_qualifier == MemberQualifier.SOME
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
    assert {public_project_id, private_project_id1, private_project_id2} == set(
        await authz.get_user_projects(regular_user1, regular_user1.id, Scope.DELETE)
    )
    assert {public_project_id, private_project_id1, private_project_id2} == set(
        await authz.get_user_projects(regular_user1, regular_user1.id, Scope.WRITE)
    )
    assert {public_project_id, private_project_id1, private_project_id2} == set(
        await authz.get_user_projects(regular_user1, regular_user1.id, Scope.READ)
    )
    assert {public_project_id, private_project_id1, private_project_id2} == set(
        await authz.get_user_projects(admin_user, admin_user.id, Scope.DELETE)
    )
    assert {public_project_id, private_project_id1, private_project_id2} == set(
        await authz.get_user_projects(admin_user, admin_user.id, Scope.WRITE)
    )
    assert {public_project_id, private_project_id1, private_project_id2} == set(
        await authz.get_user_projects(admin_user, admin_user.id, Scope.READ)
    )
    with pytest.raises(errors.Unauthorized):
        await authz.get_user_projects(anon_user, regular_user1.id, Scope.WRITE)
        await authz.get_user_projects(anon_user, regular_user1.id, Scope.DELETE)
        await authz.get_user_projects(anon_user, regular_user1.id, Scope.READ)
        await authz.get_user_projects(regular_user2, regular_user1.id, Scope.WRITE)
        await authz.get_user_projects(regular_user2, regular_user1.id, Scope.DELETE)
        await authz.get_user_projects(regular_user2, regular_user1.id, Scope.READ)
    assert {public_project_id} == set(await authz.get_user_projects(anon_user, MemberQualifier.ALL, Scope.READ))
    assert {public_project_id} == set(await authz.get_user_projects(regular_user2, regular_user2.id, Scope.READ))
    await authz.add_user(regular_user1, regular_user2.id, private_project_id1, Role.MEMBER)
    assert {public_project_id, private_project_id1} == set(
        await authz.get_user_projects(regular_user2, regular_user2.id, Scope.READ)
    )
    assert len(set(await authz.get_user_projects(regular_user2, regular_user2.id, Scope.WRITE))) == 0
    assert len(set(await authz.get_user_projects(regular_user2, regular_user2.id, Scope.DELETE))) == 0
    # Test project deletion
    await authz.delete_project(regular_user1, private_project_id1)
    assert private_project_id1 not in set(await authz.get_user_projects(regular_user1, regular_user1.id, Scope.READ))
    assert private_project_id1 not in set(await authz.get_user_projects(admin_user, admin_user.id, Scope.DELETE))
