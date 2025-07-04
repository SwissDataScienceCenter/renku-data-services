import pytest
import pytest_asyncio
from authzed.api.v1 import (
    Relationship,
    RelationshipUpdate,
    SubjectReference,
    WriteRelationshipsRequest,
)
from ulid import ULID

from renku_data_services.authz.authz import _AuthzConverter
from renku_data_services.authz.models import Member, Role, Scope, Visibility
from renku_data_services.base_models import APIUser
from renku_data_services.base_models.core import NamespacePath, ResourceType
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.errors import errors
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.namespace.models import UserNamespace
from renku_data_services.project import constants as project_constants
from renku_data_services.project.models import Project

admin_user = APIUser(is_admin=True, id="admin-id", access_token="some-token", full_name="admin")  # nosec B106
anon_user = APIUser(is_admin=False)
regular_user1 = APIUser(is_admin=False, id="user1-id", access_token="some-token1", full_name="some-user1")  # nosec B106
regular_user2 = APIUser(is_admin=False, id="user2-id", access_token="some-token2", full_name="some-user2")  # nosec B106


@pytest_asyncio.fixture
async def bootstrap_admins(app_manager_instance: DependencyManager, event_loop) -> None:
    run_migrations_for_app("common")
    authz = app_manager_instance.authz
    admins = [admin_user]
    rels: list[RelationshipUpdate] = []
    for admin in admins:
        assert admin.id is not None
        sub = SubjectReference(object=_AuthzConverter.user(admin.id))
        rels.append(
            RelationshipUpdate(
                operation=RelationshipUpdate.OPERATION_TOUCH,
                relationship=Relationship(resource=_AuthzConverter.platform(), relation="admin", subject=sub),
            )
        )
    await authz.client.WriteRelationships(WriteRelationshipsRequest(updates=rels))


@pytest.mark.asyncio
@pytest.mark.parametrize("public_project", [True, False])
async def test_adding_deleting_project(
    app_manager_instance: DependencyManager, bootstrap_admins, public_project: bool
) -> None:
    project_owner = regular_user1
    assert project_owner.id
    authz = app_manager_instance.authz
    project_id = ULID()
    project = Project(
        id=project_id,
        name=project_id,
        slug="slug",
        namespace=UserNamespace(
            id="namespace",
            created_by=project_owner.id,
            underlying_resource_id=project_owner.id,
            path=NamespacePath.from_strings("namespace"),
        ),
        visibility=Visibility.PUBLIC if public_project else Visibility.PRIVATE,
        created_by=project_owner.id,
        secrets_mount_directory=project_constants.DEFAULT_SESSION_SECRETS_MOUNT_DIR,
    )
    authz_changes = authz._add_project(project)
    await authz.client.WriteRelationships(authz_changes.apply)
    assert await authz.has_permission(project_owner, ResourceType.project, project_id, Scope.DELETE)
    assert await authz.has_permission(project_owner, ResourceType.project, project_id, Scope.WRITE)
    assert await authz.has_permission(project_owner, ResourceType.project, project_id, Scope.READ)
    assert await authz.has_permission(admin_user, ResourceType.project, project_id, Scope.DELETE)
    assert await authz.has_permission(admin_user, ResourceType.project, project_id, Scope.WRITE)
    assert await authz.has_permission(admin_user, ResourceType.project, project_id, Scope.READ)
    assert public_project == await authz.has_permission(anon_user, ResourceType.project, project_id, Scope.READ)
    assert public_project == await authz.has_permission(regular_user2, ResourceType.project, project_id, Scope.READ)
    assert not await authz.has_permission(anon_user, ResourceType.project, project_id, Scope.WRITE)
    assert not await authz.has_permission(anon_user, ResourceType.project, project_id, Scope.DELETE)
    assert not await authz.has_permission(regular_user2, ResourceType.project, project_id, Scope.WRITE)
    assert not await authz.has_permission(regular_user2, ResourceType.project, project_id, Scope.DELETE)
    authz_changes = await authz._remove_project(project_owner, project)
    await authz.client.WriteRelationships(authz_changes.apply)
    assert not await authz.has_permission(admin_user, ResourceType.project, project_id, Scope.READ)
    assert not await authz.has_permission(admin_user, ResourceType.project, project_id, Scope.WRITE)
    assert not await authz.has_permission(admin_user, ResourceType.project, project_id, Scope.DELETE)
    assert not await authz.has_permission(project_owner, ResourceType.project, project_id, Scope.READ)
    assert not await authz.has_permission(project_owner, ResourceType.project, project_id, Scope.WRITE)
    assert not await authz.has_permission(project_owner, ResourceType.project, project_id, Scope.DELETE)
    assert not await authz.has_permission(regular_user2, ResourceType.project, project_id, Scope.READ)
    assert not await authz.has_permission(regular_user2, ResourceType.project, project_id, Scope.WRITE)
    assert not await authz.has_permission(regular_user2, ResourceType.project, project_id, Scope.DELETE)


@pytest.mark.asyncio
@pytest.mark.parametrize("public_project", [True, False])
@pytest.mark.parametrize("granted_role", [Role.VIEWER, Role.EDITOR, Role.OWNER])
async def test_granting_access(
    app_manager_instance: DependencyManager, bootstrap_admins, public_project: bool, granted_role: Role
) -> None:
    project_owner = regular_user1
    assert project_owner.id
    assert regular_user2.id
    authz = app_manager_instance.authz
    project_id = ULID()
    project = Project(
        id=project_id,
        name=project_id,
        slug="slug",
        namespace=UserNamespace(
            id="namespace",
            created_by=project_owner.id,
            underlying_resource_id=project_owner.id,
            path=NamespacePath.from_strings("namespace"),
        ),
        visibility=Visibility.PUBLIC if public_project else Visibility.PRIVATE,
        created_by=project_owner.id,
    )
    authz_changes = authz._add_project(project)
    await authz.client.WriteRelationships(authz_changes.apply)
    assert public_project == await authz.has_permission(regular_user2, ResourceType.project, project_id, Scope.READ)
    assert not await authz.has_permission(regular_user2, ResourceType.project, project_id, Scope.WRITE)
    assert not await authz.has_permission(regular_user2, ResourceType.project, project_id, Scope.DELETE)
    assert not await authz.has_permission(regular_user2, ResourceType.project, project_id, Scope.CHANGE_MEMBERSHIP)
    assert public_project == await authz.has_permission(anon_user, ResourceType.project, project_id, Scope.READ)
    new_member = Member(granted_role, regular_user2.id, project_id)
    await authz.upsert_project_members(project_owner, ResourceType.project, project.id, [new_member])
    granted_role_members = await authz.members(project_owner, ResourceType.project, project_id, granted_role)
    assert regular_user2.id in [i.user_id for i in granted_role_members]
    assert await authz.has_permission(regular_user2, ResourceType.project, project_id, Scope.READ)
    assert (granted_role in [Role.OWNER, Role.EDITOR]) == await authz.has_permission(
        regular_user2, ResourceType.project, project_id, Scope.WRITE
    )
    assert (granted_role == Role.OWNER) == await authz.has_permission(
        regular_user2, ResourceType.project, project_id, Scope.DELETE
    )
    assert (granted_role == Role.OWNER) == await authz.has_permission(
        regular_user2, ResourceType.project, project_id, Scope.CHANGE_MEMBERSHIP
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("public_project", [True, False])
async def test_listing_users_with_access(
    app_manager_instance: DependencyManager, public_project: bool, bootstrap_admins
) -> None:
    project_owner = regular_user1
    assert project_owner.id
    assert regular_user2.id
    authz = app_manager_instance.authz
    project1_id = ULID()
    project1 = Project(
        id=project1_id,
        name=str(project1_id),
        slug=str(project1_id),
        namespace=UserNamespace(
            id=project_owner.id,
            created_by=project_owner.id,
            underlying_resource_id=project_owner.id,
            path=[project_owner.id],
        ),
        visibility=Visibility.PUBLIC if public_project else Visibility.PRIVATE,
        created_by=project_owner.id,
    )
    project2_id = ULID()
    project2 = Project(
        id=project2_id,
        name=str(project2_id),
        slug=str(project2_id),
        namespace=UserNamespace(
            id=regular_user2.id,
            created_by=regular_user2.id,
            underlying_resource_id=regular_user2.id,
            path=[regular_user2.id],
        ),
        visibility=Visibility.PRIVATE,
        created_by=regular_user2.id,
    )
    for p in [project1, project2]:
        changes = authz._add_project(p)
        await authz.client.WriteRelationships(changes.apply)
    proj1_users = set(await authz.users_with_permission(project_owner, ResourceType.project, project1_id, Scope.READ))
    proj2_users = set(await authz.users_with_permission(regular_user2, ResourceType.project, project2_id, Scope.READ))
    if public_project:
        assert proj1_users == {project_owner.id, admin_user.id, "*"}
    else:
        assert proj1_users == {project_owner.id, admin_user.id}
    assert proj2_users == {regular_user2.id, admin_user.id}


@pytest.mark.asyncio
async def test_listing_projects_with_access(app_manager_instance: DependencyManager, bootstrap_admins) -> None:
    authz = app_manager_instance.authz
    public_project_id = ULID()
    private_project_id1 = ULID()
    private_project_id2 = ULID()

    public_project_id_str = str(public_project_id)
    private_project_id1_str = str(private_project_id1)
    private_project_id2_str = str(private_project_id2)

    project_owner = regular_user1
    namespace = UserNamespace(
        id=project_owner.id,
        created_by=project_owner.id,
        underlying_resource_id=project_owner.id,
        path=[project_owner.id],
    )
    assert project_owner.id
    assert regular_user2.id
    public_project = Project(
        id=public_project_id,
        name=public_project_id_str,
        slug=public_project_id_str,
        namespace=namespace,
        visibility=Visibility.PUBLIC,
        created_by=project_owner.id,
    )
    private_project1 = Project(
        id=private_project_id1,
        name=private_project_id1_str,
        slug=private_project_id1_str,
        namespace=namespace,
        visibility=Visibility.PRIVATE,
        created_by=project_owner.id,
    )
    private_project2 = Project(
        id=private_project_id2,
        name=private_project_id2_str,
        slug=private_project_id2_str,
        namespace=namespace,
        visibility=Visibility.PRIVATE,
        created_by=project_owner.id,
    )
    for p in [public_project, private_project1, private_project2]:
        changes = authz._add_project(p)
        await authz.client.WriteRelationships(changes.apply)
    assert {public_project_id_str, private_project_id1_str, private_project_id2_str} == set(
        await authz.resources_with_permission(project_owner, regular_user1.id, ResourceType.project, Scope.DELETE)
    )
    assert {public_project_id_str, private_project_id1_str, private_project_id2_str} == set(
        await authz.resources_with_permission(project_owner, regular_user1.id, ResourceType.project, Scope.WRITE)
    )
    assert {public_project_id_str, private_project_id1_str, private_project_id2_str} == set(
        await authz.resources_with_permission(project_owner, regular_user1.id, ResourceType.project, Scope.READ)
    )
    assert {public_project_id_str, private_project_id1_str, private_project_id2_str} == set(
        await authz.resources_with_permission(admin_user, admin_user.id, ResourceType.project, Scope.DELETE)
    )
    assert {public_project_id_str, private_project_id1_str, private_project_id2_str} == set(
        await authz.resources_with_permission(admin_user, admin_user.id, ResourceType.project, Scope.WRITE)
    )
    assert {public_project_id_str, private_project_id1_str, private_project_id2_str} == set(
        await authz.resources_with_permission(admin_user, admin_user.id, ResourceType.project, Scope.READ)
    )
    with pytest.raises(errors.ForbiddenError):
        await authz.resources_with_permission(anon_user, project_owner.id, ResourceType.project, Scope.WRITE)
        await authz.resources_with_permission(anon_user, project_owner.id, ResourceType.project, Scope.DELETE)
        await authz.resources_with_permission(anon_user, project_owner.id, ResourceType.project, Scope.READ)
        await authz.resources_with_permission(regular_user2, project_owner.id, ResourceType.project, Scope.WRITE)
        await authz.resources_with_permission(regular_user2, project_owner.id, ResourceType.project, Scope.DELETE)
        await authz.resources_with_permission(regular_user2, project_owner.id, ResourceType.project, Scope.READ)
    assert {public_project_id_str} == set(
        await authz.resources_with_permission(anon_user, anon_user.id, ResourceType.project, Scope.READ)
    )
    assert {public_project_id_str} == set(
        await authz.resources_with_permission(regular_user2, regular_user2.id, ResourceType.project, Scope.READ)
    )
    await authz.upsert_project_members(
        project_owner,
        ResourceType.project,
        private_project1.id,
        [Member(Role.VIEWER, regular_user2.id, private_project_id1)],
    )
    assert {public_project_id_str, private_project_id1_str} == set(
        await authz.resources_with_permission(regular_user2, regular_user2.id, ResourceType.project, Scope.READ)
    )
    assert (
        len(
            set(
                await authz.resources_with_permission(
                    regular_user2, regular_user2.id, ResourceType.project, Scope.WRITE
                )
            )
        )
        == 0
    )
    assert (
        len(
            set(
                await authz.resources_with_permission(
                    regular_user2, regular_user2.id, ResourceType.project, Scope.DELETE
                )
            )
        )
        == 0
    )
    # Test project deletion
    changes = await authz._remove_project(project_owner, private_project1)
    await authz.client.WriteRelationships(changes.apply)
    assert private_project_id1_str not in set(
        await authz.resources_with_permission(admin_user, project_owner.id, ResourceType.project, Scope.READ)
    )
    assert private_project_id1_str not in set(
        await authz.resources_with_permission(admin_user, regular_user2.id, ResourceType.project, Scope.READ)
    )
    assert private_project_id1_str not in set(
        await authz.resources_with_permission(admin_user, admin_user.id, ResourceType.project, Scope.DELETE)
    )


@pytest.mark.asyncio
async def test_listing_non_public_projects(app_manager_instance: DependencyManager, bootstrap_admins) -> None:
    authz = app_manager_instance.authz
    public_project_id = ULID()
    private_project_id1 = ULID()
    private_project_id2 = ULID()

    public_project_id_str = str(public_project_id)
    private_project_id1_str = str(private_project_id1)
    private_project_id2_str = str(private_project_id2)

    namespace = UserNamespace(
        id=ULID(),
        created_by=str(regular_user1.id),
        underlying_resource_id=str(ULID()),
        path=NamespacePath.from_strings("ns-121"),
    )
    assert regular_user1.id
    assert regular_user2.id
    public_project = Project(
        id=public_project_id,
        name=public_project_id_str,
        slug=public_project_id_str,
        namespace=namespace,
        visibility=Visibility.PUBLIC,
        created_by=regular_user1.id,
    )
    private_project1 = Project(
        id=private_project_id1,
        name=private_project_id1_str,
        slug=private_project_id1_str,
        namespace=namespace,
        visibility=Visibility.PRIVATE,
        created_by=regular_user1.id,
    )
    private_project2 = Project(
        id=private_project_id2,
        name=private_project_id2_str,
        slug=private_project_id2_str,
        namespace=namespace,
        visibility=Visibility.PRIVATE,
        created_by=regular_user2.id,
    )
    for p in [public_project, private_project1, private_project2]:
        changes = authz._add_project(p)
        await authz.client.WriteRelationships(changes.apply)

    ids_user1 = await authz.resources_with_permission(
        admin_user, regular_user1.id, ResourceType.project, Scope.NON_PUBLIC_READ
    )
    ids_user2 = await authz.resources_with_permission(
        admin_user, regular_user2.id, ResourceType.project, Scope.NON_PUBLIC_READ
    )
    assert private_project_id1_str in set(ids_user1)
    assert private_project_id2_str not in set(ids_user1)
    assert public_project_id_str not in set(ids_user1)

    assert private_project_id2_str in set(ids_user2)
    assert private_project_id1_str not in set(ids_user2)
    assert public_project_id_str not in set(ids_user2)
