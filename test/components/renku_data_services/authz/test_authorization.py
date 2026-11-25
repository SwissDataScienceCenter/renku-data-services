from types import SimpleNamespace

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

from renku_data_services.authz.authz import AuthzOperation, _AuthzConverter, _Relation
from renku_data_services.authz.models import Change, Member, MembershipChange, Role, Scope, Visibility
from renku_data_services.base_models import APIUser
from renku_data_services.base_models.core import NamespacePath, ResourceType
from renku_data_services.crc.models import (
    DeletedResourcePool,
    ResourcePoolMembershipChange,
)
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
        for obj_type in (ResourceType.user, ResourceType.anonymous_user):
            updates.append(
                RelationshipUpdate(
                    operation=RelationshipUpdate.OPERATION_TOUCH,
                    relationship=Relationship(
                        resource=pool_ref,
                        relation="public_viewer",
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


def _rel_member(
    pool_id: int,
    relation: str,
    member_id: str,
    member_type: ResourceType,
    *,
    op: int = RelationshipUpdate.OPERATION_TOUCH,
) -> RelationshipUpdate:
    """Helper to create a relationship for a polymorphic member."""
    return RelationshipUpdate(
        operation=op,
        relationship=Relationship(
            resource=_AuthzConverter.resource_pool(pool_id),
            relation=relation,
            subject=SubjectReference(object=ObjectReference(object_type=member_type, object_id=member_id)),
        ),
    )


def _rel_generic(
    res_type: ResourceType,
    res_id: str | int,
    relation: str,
    sub_type: ResourceType,
    sub_id: str,
    *,
    op: int = RelationshipUpdate.OPERATION_TOUCH,
) -> RelationshipUpdate:
    """Helper to create any relationship in Authzed."""
    # Use converter for type-specific object references if available, otherwise fallback
    res_ref = (
        _AuthzConverter.get_resource_ref(res_type, res_id)
        if hasattr(_AuthzConverter, "get_resource_ref")
        else ObjectReference(object_type=res_type, object_id=str(res_id))
    )
    sub_ref = (
        _AuthzConverter.get_resource_ref(sub_type, sub_id)
        if hasattr(_AuthzConverter, "get_resource_ref")
        else ObjectReference(object_type=sub_type, object_id=sub_id)
    )

    return RelationshipUpdate(
        operation=op,
        relationship=Relationship(
            resource=res_ref,
            relation=relation,
            subject=SubjectReference(object=sub_ref),
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
    assert await authz.has_permission(admin_user, ResourceType.resource_pool, POOL_ID, Scope.READ)
    assert await authz.has_permission(admin_user, ResourceType.resource_pool, POOL_ID, Scope.WRITE)

    # Regular user and anon: use depends on public, write is always denied
    assert public_pool == await authz.has_permission(regular_user1, ResourceType.resource_pool, POOL_ID, Scope.READ)
    assert public_pool == await authz.has_permission(anon_user, ResourceType.resource_pool, POOL_ID, Scope.READ)
    assert not await authz.has_permission(regular_user1, ResourceType.resource_pool, POOL_ID, Scope.WRITE)
    assert not await authz.has_permission(anon_user, ResourceType.resource_pool, POOL_ID, Scope.WRITE)


@pytest.mark.asyncio
@pytest.mark.parametrize("public_pool", [True, False])
async def test_resource_pool_member_access(
    app_manager_instance: DependencyManager, bootstrap_admins, public_pool: bool
) -> None:
    """An explicit member can use a pool regardless of visibility; non-members still follow public rules."""
    authz = app_manager_instance.authz
    updates = _pool_updates(POOL_ID, public=public_pool) + [_rel(POOL_ID, _Relation.viewer.value, regular_user1.id)]
    await authz.client.WriteRelationships(WriteRelationshipsRequest(updates=updates))

    # Member can always use
    assert await authz.has_permission(regular_user1, ResourceType.resource_pool, POOL_ID, Scope.READ)
    # Member still cannot write
    assert not await authz.has_permission(regular_user1, ResourceType.resource_pool, POOL_ID, Scope.WRITE)
    # Non-member follows public rules
    assert public_pool == await authz.has_permission(regular_user2, ResourceType.resource_pool, POOL_ID, Scope.READ)


@pytest.mark.asyncio
@pytest.mark.parametrize("public_pool", [True, False])
@pytest.mark.parametrize("is_member", [True, False])
async def test_resource_pool_prohibited_blocks_access(
    app_manager_instance: DependencyManager, bootstrap_admins, public_pool: bool, is_member: bool
) -> None:
    """A prohibited user is blocked regardless of public visibility or membership."""
    authz = app_manager_instance.authz
    updates = _pool_updates(POOL_ID, public=public_pool) + [_rel(POOL_ID, _Relation.prohibited.value, regular_user1.id)]
    if is_member:
        updates.append(_rel(POOL_ID, _Relation.viewer.value, regular_user1.id))
    await authz.client.WriteRelationships(WriteRelationshipsRequest(updates=updates))

    assert not await authz.has_permission(regular_user1, ResourceType.resource_pool, POOL_ID, Scope.READ)


@pytest.mark.asyncio
async def test_resource_pool_admin_bypasses_prohibited(
    app_manager_instance: DependencyManager, bootstrap_admins
) -> None:
    """Admin bypasses the prohibited flag via the platform->is_admin union."""
    authz = app_manager_instance.authz
    updates = _pool_updates(POOL_ID, public=True) + [_rel(POOL_ID, _Relation.prohibited.value, admin_user.id)]
    await authz.client.WriteRelationships(WriteRelationshipsRequest(updates=updates))

    assert await authz.has_permission(admin_user, ResourceType.resource_pool, POOL_ID, Scope.READ)


@pytest.mark.asyncio
async def test_resource_pool_add_remove_member(app_manager_instance: DependencyManager, bootstrap_admins) -> None:
    """Adding and removing a member dynamically grants and revokes access."""
    authz = app_manager_instance.authz
    await authz.client.WriteRelationships(WriteRelationshipsRequest(updates=_pool_updates(POOL_ID, public=False)))

    assert not await authz.has_permission(regular_user1, ResourceType.resource_pool, POOL_ID, Scope.READ)

    await authz.client.WriteRelationships(
        WriteRelationshipsRequest(updates=[_rel(POOL_ID, _Relation.viewer.value, regular_user1.id)])
    )
    assert await authz.has_permission(regular_user1, ResourceType.resource_pool, POOL_ID, Scope.READ)

    await authz.client.WriteRelationships(
        WriteRelationshipsRequest(
            updates=[_rel(POOL_ID, _Relation.viewer.value, regular_user1.id, op=RelationshipUpdate.OPERATION_DELETE)]
        )
    )
    assert not await authz.has_permission(regular_user1, ResourceType.resource_pool, POOL_ID, Scope.READ)


@pytest.mark.asyncio
async def test_resource_pool_add_remove_prohibited(app_manager_instance: DependencyManager, bootstrap_admins) -> None:
    """Adding and removing a prohibited relation dynamically blocks and restores access."""
    authz = app_manager_instance.authz
    await authz.client.WriteRelationships(WriteRelationshipsRequest(updates=_pool_updates(POOL_ID, public=True)))

    assert await authz.has_permission(regular_user1, ResourceType.resource_pool, POOL_ID, Scope.READ)

    await authz.client.WriteRelationships(
        WriteRelationshipsRequest(updates=[_rel(POOL_ID, _Relation.prohibited.value, regular_user1.id)])
    )
    assert not await authz.has_permission(regular_user1, ResourceType.resource_pool, POOL_ID, Scope.READ)

    await authz.client.WriteRelationships(
        WriteRelationshipsRequest(
            updates=[
                _rel(POOL_ID, _Relation.prohibited.value, regular_user1.id, op=RelationshipUpdate.OPERATION_DELETE)
            ]
        )
    )
    assert await authz.has_permission(regular_user1, ResourceType.resource_pool, POOL_ID, Scope.READ)


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
                _rel(pool_a, _Relation.viewer.value, regular_user1.id),
                _rel(pool_b, _Relation.prohibited.value, regular_user1.id),
            ]
        )
    )

    assert await authz.has_permission(regular_user1, ResourceType.resource_pool, pool_a, Scope.READ)
    assert not await authz.has_permission(regular_user1, ResourceType.resource_pool, pool_b, Scope.READ)


@pytest.mark.asyncio
async def test_resource_pool_member_relationships_subject_types(app_manager_instance: DependencyManager):
    """Verify that _resource_pool_membership_changes_to_authz_change uses correct subject types."""
    authz = app_manager_instance.authz
    pool_id = 9999
    group_id = str(ULID())
    project_id = str(ULID())

    pool_change = ResourcePoolMembershipChange(
        changes=[
            MembershipChange(
                Member(
                    role=Role.VIEWER,
                    user_id="user-1",
                    resource_id=pool_id,
                    resource_type=ResourceType.resource_pool,
                    subject_type=None,
                ),
                Change.ADD,
            ),
            MembershipChange(
                Member(
                    role=Role.VIEWER,
                    user_id=group_id,
                    resource_id=pool_id,
                    resource_type=ResourceType.resource_pool,
                    subject_type=ResourceType.group,
                ),
                Change.ADD,
            ),
            MembershipChange(
                Member(
                    role=Role.VIEWER,
                    user_id=project_id,
                    resource_id=pool_id,
                    resource_type=ResourceType.resource_pool,
                    subject_type=ResourceType.project,
                ),
                Change.ADD,
            ),
        ]
    )

    authz_change = authz._resource_pool_membership_changes_to_authz_change(pool_change, AuthzOperation.create)

    updates = authz_change.apply.updates
    assert len(updates) == 3

    # User subject
    assert updates[0].relationship.relation == _Relation.viewer.value
    assert updates[0].relationship.subject.object.object_type == ResourceType.user
    assert updates[0].relationship.subject.object.object_id == "user-1"

    # Group subject
    assert updates[1].relationship.relation == _Relation.group_viewer.value
    assert updates[1].relationship.subject.object.object_type == ResourceType.group
    assert updates[1].relationship.subject.object.object_id == group_id

    # Project subject
    assert updates[2].relationship.relation == _Relation.project_viewer.value
    assert updates[2].relationship.subject.object.object_type == ResourceType.project
    assert updates[2].relationship.subject.object.object_id == project_id


_ADD_DELETE_BASE = 9100
_UNDO_BASE = 9110
_VISIBILITY_BASE = 9120
_LOOKUP_BASE = 9130
_CLEANUP_BASE = 9140


async def _assert_pool_access(
    authz,
    pool_id: int,
    *,
    admin_use: bool = True,
    admin_write: bool = True,
    user_use: bool,
    anon_use: bool,
) -> None:
    """Assert USE / WRITE for admin, regular_user1 and anon_user on *pool_id*.

    regular_user1 and anon_user are never expected to have WRITE — those two
    assertions are always ``False`` and included automatically.
    """
    assert await authz.has_permission(admin_user, ResourceType.resource_pool, pool_id, Scope.READ) is admin_use
    assert await authz.has_permission(admin_user, ResourceType.resource_pool, pool_id, Scope.WRITE) is admin_write
    assert await authz.has_permission(regular_user1, ResourceType.resource_pool, pool_id, Scope.READ) is user_use
    assert await authz.has_permission(regular_user1, ResourceType.resource_pool, pool_id, Scope.WRITE) is False
    assert await authz.has_permission(anon_user, ResourceType.resource_pool, pool_id, Scope.READ) is anon_use
    assert await authz.has_permission(anon_user, ResourceType.resource_pool, pool_id, Scope.WRITE) is False


async def _create_pool_in_authz(authz, pool_id: int, *, public: bool) -> None:
    """Shorthand: call ``_add_resource_pool`` and write the result to SpiceDB."""
    change = authz._add_resource_pool(SimpleNamespace(id=pool_id, public=public))
    await authz.client.WriteRelationships(change.apply)


@pytest.mark.asyncio
@pytest.mark.parametrize("public_pool", [True, False], ids=["public", "private"])
async def test_resource_pool_add_delete_authz(
    app_manager_instance: DependencyManager, bootstrap_admins, public_pool: bool
) -> None:
    """_add_resource_pool creates correct rels; _remove_resource_pool cleans them all."""
    authz = app_manager_instance.authz
    pool_id = _ADD_DELETE_BASE + int(public_pool)

    await _create_pool_in_authz(authz, pool_id, public=public_pool)
    await _assert_pool_access(authz, pool_id, user_use=public_pool, anon_use=public_pool)

    remove_change = await authz._remove_resource_pool(admin_user, DeletedResourcePool(id=pool_id))
    await authz.client.WriteRelationships(remove_change.apply)

    await _assert_pool_access(authz, pool_id, admin_use=False, admin_write=False, user_use=False, anon_use=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("public_pool", [True, False], ids=["public", "private"])
async def test_resource_pool_add_undo(
    app_manager_instance: DependencyManager, bootstrap_admins, public_pool: bool
) -> None:
    """Applying the undo payload from _add_resource_pool fully reverses creation."""
    authz = app_manager_instance.authz
    pool_id = _UNDO_BASE + int(public_pool)

    change = authz._add_resource_pool(SimpleNamespace(id=pool_id, public=public_pool))
    await authz.client.WriteRelationships(change.apply)
    await _assert_pool_access(authz, pool_id, user_use=public_pool, anon_use=public_pool)

    # Undo — simulates DB-rollback recovery path
    await authz.client.WriteRelationships(change.undo)
    await _assert_pool_access(authz, pool_id, admin_use=False, admin_write=False, user_use=False, anon_use=False)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "initial_public,new_public",
    [
        (True, False),
        (False, True),
        (True, True),
        (False, False),
    ],
    ids=["public_to_private", "private_to_public", "public_to_public(noop)", "private_to_private(noop)"],
)
async def test_resource_pool_visibility_update(
    app_manager_instance: DependencyManager,
    bootstrap_admins,
    initial_public: bool,
    new_public: bool,
) -> None:
    """_update_resource_pool_visibility adds/removes public_viewer wildcards correctly."""
    authz = app_manager_instance.authz
    pool_id = _VISIBILITY_BASE + int(initial_public) * 2 + int(new_public)

    await _create_pool_in_authz(authz, pool_id, public=initial_public)
    await _assert_pool_access(authz, pool_id, user_use=initial_public, anon_use=initial_public)

    vis_change = await authz._update_resource_pool_visibility(
        admin_user, SimpleNamespace(id=pool_id, public=new_public)
    )
    await authz.client.WriteRelationships(vis_change.apply)

    await _assert_pool_access(authz, pool_id, user_use=new_public, anon_use=new_public)

    if initial_public == new_public:
        assert len(vis_change.apply.updates) == 0, "No-op transition should produce no apply ops"
        assert len(vis_change.undo.updates) == 0, (
            f"No-op transition ({initial_public}->{new_public}) produced "
            f"{len(vis_change.undo.updates)} undo op(s) that would corrupt state on rollback"
        )


@pytest.mark.asyncio
async def test_resource_pool_lookup_resources(app_manager_instance: DependencyManager, bootstrap_admins) -> None:
    """resources_with_permission returns correct pool IDs per user role."""
    authz = app_manager_instance.authz
    public_id, private_id = _LOOKUP_BASE, _LOOKUP_BASE + 1

    for pid, public in [(public_id, True), (private_id, False)]:
        await _create_pool_in_authz(authz, pid, public=public)

    # Admin sees both
    admin_pools = set(
        await authz.resources_with_permission(admin_user, admin_user.id, ResourceType.resource_pool, Scope.READ)
    )
    assert {str(public_id), str(private_id)}.issubset(admin_pools)

    # Regular user sees only public
    user_pools = set(
        await authz.resources_with_permission(regular_user1, regular_user1.id, ResourceType.resource_pool, Scope.READ)
    )
    assert str(public_id) in user_pools
    assert str(private_id) not in user_pools

    # Add regular_user1 as member → now sees both
    await authz.client.WriteRelationships(
        WriteRelationshipsRequest(updates=[_rel(private_id, _Relation.viewer, regular_user1.id)])
    )
    user_pools = set(
        await authz.resources_with_permission(regular_user1, regular_user1.id, ResourceType.resource_pool, Scope.READ)
    )
    assert str(private_id) in user_pools

    # Anon still only sees public
    anon_pools = set(
        await authz.resources_with_permission(anon_user, anon_user.id, ResourceType.resource_pool, Scope.READ)
    )
    assert str(public_id) in anon_pools
    assert str(private_id) not in anon_pools


@pytest.mark.asyncio
async def test_resource_pool_delete_cleans_all_relations(
    app_manager_instance: DependencyManager, bootstrap_admins
) -> None:
    """_remove_resource_pool removes ALL rels including member and prohibited."""
    authz = app_manager_instance.authz
    pool_id = _CLEANUP_BASE

    await _create_pool_in_authz(authz, pool_id, public=True)
    await authz.client.WriteRelationships(
        WriteRelationshipsRequest(
            updates=[
                _rel(pool_id, _Relation.viewer, regular_user1.id),
                _rel(pool_id, _Relation.prohibited, regular_user2.id),
            ]
        )
    )

    assert await authz.has_permission(regular_user1, ResourceType.resource_pool, pool_id, Scope.READ)
    assert not await authz.has_permission(regular_user2, ResourceType.resource_pool, pool_id, Scope.READ)

    remove_change = await authz._remove_resource_pool(admin_user, DeletedResourcePool(id=pool_id))
    await authz.client.WriteRelationships(remove_change.apply)

    await _assert_pool_access(authz, pool_id, admin_use=False, admin_write=False, user_use=False, anon_use=False)
    assert not await authz.has_permission(regular_user2, ResourceType.resource_pool, pool_id, Scope.READ)


_POLY_BASE = 9500


@pytest.mark.asyncio
async def test_resource_pool_polymorphic_inheritance(app_manager_instance: DependencyManager, bootstrap_admins) -> None:
    """Verify that members of a group or project gain access via direct_member traversal."""
    authz = app_manager_instance.authz
    pool_id = _POLY_BASE + 1
    user_id = "user_poly_1"
    group_id = "group_poly_1"
    project_id = "project_poly_1"

    # Setup: Admin and basic pool setup
    await authz.client.WriteRelationships(WriteRelationshipsRequest(updates=_pool_updates(pool_id, public=False)))

    # 1. Group inheritance: pool -> group_viewer -> group -> user
    updates = [
        _rel_member(pool_id, "group_viewer", group_id, ResourceType.group),
        _rel_generic(ResourceType.group, group_id, "viewer", ResourceType.user, user_id),
    ]
    await authz.client.WriteRelationships(WriteRelationshipsRequest(updates=updates))
    assert await authz.has_permission(APIUser(id=user_id), ResourceType.resource_pool, pool_id, Scope.READ)

    # 2. Project inheritance: pool -> project_viewer -> project -> user
    pool_id2 = _POLY_BASE + 2
    await authz.client.WriteRelationships(WriteRelationshipsRequest(updates=_pool_updates(pool_id2, public=False)))
    updates = [
        _rel_member(pool_id2, "project_viewer", project_id, ResourceType.project),
        _rel_generic(ResourceType.project, project_id, "viewer", ResourceType.user, user_id),
    ]
    await authz.client.WriteRelationships(WriteRelationshipsRequest(updates=updates))
    assert await authz.has_permission(APIUser(id=user_id), ResourceType.resource_pool, pool_id2, Scope.READ)


@pytest.mark.asyncio
async def test_resource_pool_polymorphic_prohibition(app_manager_instance: DependencyManager, bootstrap_admins) -> None:
    """Verify that the prohibited relation blocks access regardless of membership type."""
    authz = app_manager_instance.authz
    pool_id = _POLY_BASE + 3
    user_id = "user_prohibit_1"
    group_id = "group_prohibit_1"

    await authz.client.WriteRelationships(WriteRelationshipsRequest(updates=_pool_updates(pool_id, public=False)))

    # Setup: user is in group, group is a viewer of pool, but user is prohibited
    updates = [
        _rel_member(pool_id, "group_viewer", group_id, ResourceType.group),
        _rel_generic(ResourceType.group, group_id, "viewer", ResourceType.user, user_id),
        _rel(pool_id, "prohibited", user_id),
    ]
    await authz.client.WriteRelationships(WriteRelationshipsRequest(updates=updates))
    assert not await authz.has_permission(APIUser(id=user_id), ResourceType.resource_pool, pool_id, Scope.READ)


@pytest.mark.asyncio
async def test_resource_pool_admin_bypass_polymorphic(
    app_manager_instance: DependencyManager, bootstrap_admins
) -> None:
    """Verify that admins still bypass prohibition even in polymorphic pools."""
    authz = app_manager_instance.authz
    pool_id = _POLY_BASE + 4

    await authz.client.WriteRelationships(WriteRelationshipsRequest(updates=_pool_updates(pool_id, public=False)))
    await authz.client.WriteRelationships(
        WriteRelationshipsRequest(updates=[_rel(pool_id, "prohibited", admin_user.id)])
    )
    assert await authz.has_permission(admin_user, ResourceType.resource_pool, pool_id, Scope.READ)


@pytest.mark.asyncio
async def test_resource_pool_no_indirect_inheritance(app_manager_instance: DependencyManager, bootstrap_admins) -> None:
    """Verify that only direct_member is traversed, not nested namespaces."""
    authz = app_manager_instance.authz
    pool_id = _POLY_BASE + 5
    user_id = "user_indirect_1"
    project_id = "project_indirect_1"
    ns_id = "ns_indirect_1"

    await authz.client.WriteRelationships(WriteRelationshipsRequest(updates=_pool_updates(pool_id, public=False)))

    # Setup: pool -> project_viewer -> project -> namespace -> user
    updates = [
        _rel_member(pool_id, "project_viewer", project_id, ResourceType.project),
        _rel_generic(ResourceType.project, project_id, "project_namespace", ResourceType.user_namespace, ns_id),
        _rel_generic(ResourceType.user_namespace, ns_id, "owner", ResourceType.user, user_id),
    ]
    await authz.client.WriteRelationships(WriteRelationshipsRequest(updates=updates))
    assert not await authz.has_permission(APIUser(id=user_id), ResourceType.resource_pool, pool_id, Scope.READ)
