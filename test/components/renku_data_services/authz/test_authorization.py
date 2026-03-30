import pytest
import pytest_asyncio
from authzed.api.v1 import (
    ObjectReference,
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
regular_user3 = APIUser(is_admin=False, id="user3-id", access_token="some-token3", full_name="some-user3")  # nosec B106


POOL_ID = 9001


def _pool_updates(pool_id: int, *, public: bool) -> list[RelationshipUpdate]:
    """Build all relationship updates needed to create a resource pool in Authzed."""
    pool_ref = _AuthzConverter.resource_pool(pool_id)
    updates = [
        RelationshipUpdate(
            operation=RelationshipUpdate.OPERATION_TOUCH,
            relationship=Relationship(
                resource=pool_ref,
                relation="resource_pool_platform",
                subject=SubjectReference(object=_AuthzConverter.platform()),
            ),
        ),
    ]
    if public:
        for obj_type in ("user", "anonymous_user"):
            updates.append(
                RelationshipUpdate(
                    operation=RelationshipUpdate.OPERATION_TOUCH,
                    relationship=Relationship(
                        resource=pool_ref,
                        relation="public_user",
                        subject=SubjectReference(object=ObjectReference(object_type=obj_type, object_id="*")),
                    ),
                )
            )
    return updates


def _rel(
    pool_id: int, relation: str, user_id: str, *, op: int = RelationshipUpdate.OPERATION_TOUCH
) -> RelationshipUpdate:
    return RelationshipUpdate(
        operation=op,
        relationship=Relationship(
            resource=_AuthzConverter.resource_pool(pool_id),
            relation=relation,
            subject=SubjectReference(object=_AuthzConverter.user(user_id)),
        ),
    )


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


@pytest.mark.asyncio
@pytest.mark.parametrize("public_pool", [True, False])
async def test_resource_pool_base_access(
    app_manager_instance: DependencyManager, bootstrap_admins, public_pool: bool
) -> None:
    """Base access: public pools are open to everyone; private pools block non-members."""
    authz = app_manager_instance.authz
    await authz.client.WriteRelationships(WriteRelationshipsRequest(updates=_pool_updates(POOL_ID, public=public_pool)))

    # Admin can always use and write
    assert await authz.has_permission(admin_user, ResourceType.resource_pool, POOL_ID, Scope.USE)
    assert await authz.has_permission(admin_user, ResourceType.resource_pool, POOL_ID, Scope.WRITE)

    # Regular user and anon: use depends on public, write is always denied
    assert public_pool == await authz.has_permission(regular_user1, ResourceType.resource_pool, POOL_ID, Scope.USE)
    assert public_pool == await authz.has_permission(anon_user, ResourceType.resource_pool, POOL_ID, Scope.USE)
    assert not await authz.has_permission(regular_user1, ResourceType.resource_pool, POOL_ID, Scope.WRITE)
    assert not await authz.has_permission(anon_user, ResourceType.resource_pool, POOL_ID, Scope.WRITE)


@pytest.mark.asyncio
@pytest.mark.parametrize("public_pool", [True, False])
async def test_resource_pool_member_access(
    app_manager_instance: DependencyManager, bootstrap_admins, public_pool: bool
) -> None:
    """An explicit member can use a pool regardless of visibility; non-members still follow public rules."""
    authz = app_manager_instance.authz
    updates = _pool_updates(POOL_ID, public=public_pool) + [_rel(POOL_ID, "member", regular_user1.id)]
    await authz.client.WriteRelationships(WriteRelationshipsRequest(updates=updates))

    # Member can always use
    assert await authz.has_permission(regular_user1, ResourceType.resource_pool, POOL_ID, Scope.USE)
    # Member still cannot write
    assert not await authz.has_permission(regular_user1, ResourceType.resource_pool, POOL_ID, Scope.WRITE)
    # Non-member follows public rules
    assert public_pool == await authz.has_permission(regular_user2, ResourceType.resource_pool, POOL_ID, Scope.USE)


@pytest.mark.asyncio
@pytest.mark.parametrize("public_pool", [True, False])
@pytest.mark.parametrize("is_member", [True, False])
async def test_resource_pool_prohibited_blocks_access(
    app_manager_instance: DependencyManager, bootstrap_admins, public_pool: bool, is_member: bool
) -> None:
    """A prohibited user is blocked regardless of public visibility or membership."""
    authz = app_manager_instance.authz
    updates = _pool_updates(POOL_ID, public=public_pool) + [_rel(POOL_ID, "prohibited", regular_user1.id)]
    if is_member:
        updates.append(_rel(POOL_ID, "member", regular_user1.id))
    await authz.client.WriteRelationships(WriteRelationshipsRequest(updates=updates))

    assert not await authz.has_permission(regular_user1, ResourceType.resource_pool, POOL_ID, Scope.USE)


@pytest.mark.asyncio
async def test_resource_pool_admin_bypasses_prohibited(
    app_manager_instance: DependencyManager, bootstrap_admins
) -> None:
    """Admin bypasses the prohibited flag via the platform->is_admin union."""
    authz = app_manager_instance.authz
    updates = _pool_updates(POOL_ID, public=True) + [_rel(POOL_ID, "prohibited", admin_user.id)]
    await authz.client.WriteRelationships(WriteRelationshipsRequest(updates=updates))

    assert await authz.has_permission(admin_user, ResourceType.resource_pool, POOL_ID, Scope.USE)


@pytest.mark.asyncio
async def test_resource_pool_add_remove_member(app_manager_instance: DependencyManager, bootstrap_admins) -> None:
    """Adding and removing a member dynamically grants and revokes access."""
    authz = app_manager_instance.authz
    await authz.client.WriteRelationships(WriteRelationshipsRequest(updates=_pool_updates(POOL_ID, public=False)))

    assert not await authz.has_permission(regular_user1, ResourceType.resource_pool, POOL_ID, Scope.USE)

    await authz.client.WriteRelationships(
        WriteRelationshipsRequest(updates=[_rel(POOL_ID, "member", regular_user1.id)])
    )
    assert await authz.has_permission(regular_user1, ResourceType.resource_pool, POOL_ID, Scope.USE)

    await authz.client.WriteRelationships(
        WriteRelationshipsRequest(
            updates=[_rel(POOL_ID, "member", regular_user1.id, op=RelationshipUpdate.OPERATION_DELETE)]
        )
    )
    assert not await authz.has_permission(regular_user1, ResourceType.resource_pool, POOL_ID, Scope.USE)


@pytest.mark.asyncio
async def test_resource_pool_add_remove_prohibited(app_manager_instance: DependencyManager, bootstrap_admins) -> None:
    """Adding and removing a prohibited relation dynamically blocks and restores access."""
    authz = app_manager_instance.authz
    await authz.client.WriteRelationships(WriteRelationshipsRequest(updates=_pool_updates(POOL_ID, public=True)))

    assert await authz.has_permission(regular_user1, ResourceType.resource_pool, POOL_ID, Scope.USE)

    await authz.client.WriteRelationships(
        WriteRelationshipsRequest(updates=[_rel(POOL_ID, "prohibited", regular_user1.id)])
    )
    assert not await authz.has_permission(regular_user1, ResourceType.resource_pool, POOL_ID, Scope.USE)

    await authz.client.WriteRelationships(
        WriteRelationshipsRequest(
            updates=[_rel(POOL_ID, "prohibited", regular_user1.id, op=RelationshipUpdate.OPERATION_DELETE)]
        )
    )
    assert await authz.has_permission(regular_user1, ResourceType.resource_pool, POOL_ID, Scope.USE)


@pytest.mark.asyncio
async def test_resource_pool_isolation(app_manager_instance: DependencyManager, bootstrap_admins) -> None:
    """Membership and prohibition on one pool do not leak to another."""
    pool_a, pool_b = 9001, 9002
    authz = app_manager_instance.authz
    await authz.client.WriteRelationships(
        WriteRelationshipsRequest(
            updates=_pool_updates(pool_a, public=False)
            + _pool_updates(pool_b, public=True)
            + [
                _rel(pool_a, "member", regular_user1.id),
                _rel(pool_b, "prohibited", regular_user1.id),
            ]
        )
    )

    assert await authz.has_permission(regular_user1, ResourceType.resource_pool, pool_a, Scope.USE)
    assert not await authz.has_permission(regular_user1, ResourceType.resource_pool, pool_b, Scope.USE)
