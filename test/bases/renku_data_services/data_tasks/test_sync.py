import json
import re
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from typing import Any, Union
from uuid import uuid4

import pytest
from authzed.api.v1 import (
    Consistency,
    DeleteRelationshipsRequest,
    ReadRelationshipsRequest,
    Relationship,
    RelationshipFilter,
    RelationshipUpdate,
    SubjectReference,
    WriteRelationshipsRequest,
)
from ulid import ULID

from renku_data_services.authz.admin_sync import sync_admins_from_keycloak
from renku_data_services.authz.authz import Authz, ResourceType, _AuthzConverter, _Relation
from renku_data_services.authz.config import AuthzConfig
from renku_data_services.authz.models import Role, UnsavedMember
from renku_data_services.base_api.pagination import PaginationRequest
from renku_data_services.base_models import APIUser
from renku_data_services.base_models.core import NamespacePath, Slug
from renku_data_services.data_tasks.config import Config
from renku_data_services.data_tasks.dependencies import DependencyManager
from renku_data_services.data_tasks.task_defs import (
    bootstrap_user_namespaces,
    fix_mismatched_project_namespace_ids,
    migrate_groups_make_all_public,
    migrate_user_namespaces_make_all_public,
)
from renku_data_services.db_config import DBConfig
from renku_data_services.errors import errors
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.namespace.apispec import (
    GroupPostRequest,
)
from renku_data_services.namespace.models import UserNamespace
from renku_data_services.namespace.orm import NamespaceORM
from renku_data_services.project.models import UnsavedProject
from renku_data_services.users.dummy_kc_api import DummyKeycloakAPI
from renku_data_services.users.models import KeycloakAdminEvent, UnsavedUserInfo, UserInfo, UserInfoFieldUpdate
from renku_data_services.users.orm import UserORM


@pytest.fixture
def get_app_manager(db_instance: DBConfig, authz_instance: AuthzConfig):
    def _get_dependency_manager(kc_api: DummyKeycloakAPI, total_user_sync: bool = False) -> DependencyManager:
        config = Config.from_env()
        config.db = db_instance
        dm = DependencyManager.from_env(config)
        run_migrations_for_app("common")
        return dm

    yield _get_dependency_manager


def get_kc_users(updates: list[UserInfo]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for update in updates:
        output.append(update.to_keycloak_dict())
    return output


def get_kc_user_update_events(updates: list[UserInfoFieldUpdate]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for update in updates:
        output.append(
            {
                "time": int(update.timestamp_utc.timestamp() * 1000),
                "type": "UPDATE_PROFILE",
                "realmId": "61ae7898-50da-4088-a90e-f97002b1fb03",
                "clientId": "account",
                "userId": update.user_id,
                "ipAddress": "192.168.0.128",
                "details": {
                    f"previous_{update.field_name}": update.old_value,
                    "context": "ACCOUNT",
                    f"updated_{update.field_name}": update.new_value,
                },
            }
        )
    return output


def get_kc_user_create_events(updates: list[UserInfo]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for update in updates:
        output.append(
            {
                "time": int(datetime.utcnow().timestamp() * 1000),
                "type": "REGISTER",
                "realmId": "61ae7898-50da-4088-a90e-f97002b1fb03",
                "clientId": "renku-ui",
                "userId": update.id,
                "ipAddress": "192.168.0.128",
                "details": {
                    "auth_method": "openid-connect",
                    "auth_type": "code",
                    "register_method": "form",
                    "last_name": update.last_name,
                    "redirect_uri": "https://dev.renku.ch/ui-server/auth/callback",
                    "first_name": update.first_name,
                    "code_id": "a6d6bb21-2dd2-4bd2-b8ac-d0755b50d097",
                    "email": update.email,
                    "username": update.email,
                },
            }
        )
    return output


def get_kc_admin_events(updates: list[tuple[UserInfo, KeycloakAdminEvent]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for user, event_type in updates:
        update = {
            "time": int(datetime.utcnow().timestamp() / 1000),
            "realmId": "c379ffd2-9e17-4dfe-b28b-dcacdda5086c",
            "authDetails": {
                "realmId": "95061e0e-a731-4152-9dd2-e26196a748c8",
                "clientId": "1cdaeb95-56dc-4fa7-b7ce-17bc5ea38979",
                "userId": user.id,
                "ipAddress": "192.168.0.128",
            },
            "operationType": event_type.value,
            "resourceType": "USER",
            "resourcePath": f"users/{user.id}",
        }
        if event_type != KeycloakAdminEvent.DELETE:
            payload = {
                "enabled": True,
                "emailVerified": False,
                "firstName": user.first_name,
                "lastName": user.last_name,
                "email": user.email,
                "requiredActions": [],
            }
            update["representation"] = json.dumps(payload)
        output.append(update)
    return output


def get_kc_roles(role_names: list[str]) -> dict[str, list[dict[str, Union[bool, str]]]]:
    return {
        "realmMappings": [
            {
                "id": str(uuid4()),
                "name": role_name,
                "composite": False,
                "clientRole": False,
                "containerId": str(uuid4()),
            }
            for role_name in role_names
        ]
    }


@pytest.mark.asyncio
async def test_total_users_sync(get_app_manager: Callable[..., DependencyManager], admin_user: APIUser) -> None:
    user1 = UserInfo(
        id="user-1-id",
        first_name="John",
        last_name="Doe",
        email="john.doe@gmail.com",
        namespace=UserNamespace(
            id="user-1-id",
            underlying_resource_id="user-1-id",
            created_by="user-1-id",
            path=NamespacePath.from_strings("user-1"),
        ),
    )
    user2 = UserInfo(
        id="user-2-id",
        first_name="Jane",
        last_name="Doe",
        email="jane.doe@gmail.com",
        namespace=UserNamespace(
            id="user-2-id",
            underlying_resource_id="user-2-id",
            created_by="user-2-id",
            path=NamespacePath.from_strings("user-2"),
        ),
    )
    assert admin_user.id
    admin_user_info = UserInfo(
        id=admin_user.id,
        first_name=admin_user.first_name,
        last_name=admin_user.last_name,
        email=admin_user.email,
        namespace=UserNamespace(
            id=admin_user.id,
            underlying_resource_id=admin_user.id,
            created_by=admin_user.id,
            path=NamespacePath.from_strings("admin"),
        ),
    )
    user_roles = {admin_user.id: get_kc_roles(["renku-admin"])}
    kc_api = DummyKeycloakAPI(users=get_kc_users([user1, user2, admin_user_info]), user_roles=user_roles)
    dm = get_app_manager(kc_api)
    dm.kc_api = kc_api
    db_users = await dm.syncer.user_repo.get_users(admin_user)
    kc_users = [UserInfo.from_kc_user_payload(user) for user in dm.kc_api.get_users()]
    kc_users.append(
        UnsavedUserInfo(
            id=admin_user.id,
            first_name=admin_user.first_name,
            last_name=admin_user.last_name,
            email=admin_user.email,
        )
    )
    assert set(u.id for u in kc_users) == set([user1.id, user2.id, admin_user_info.id])
    assert len(db_users) == 1  # listing users add the requesting user if not present
    await dm.syncer.users_sync(kc_api)
    db_users = await dm.syncer.user_repo.get_users(admin_user)
    assert set(u.id for u in kc_users) == set(u.id for u in db_users)
    # Make sure doing users sync again does not change anything and works
    await dm.syncer.users_sync(kc_api)
    db_users = await dm.syncer.user_repo.get_users(admin_user)
    assert set(u.id for u in kc_users) == set(u.id for u in db_users)
    # Make sure that the addition of the users resulted in the creation of namespaces
    nss, _ = await dm.syncer.group_repo.get_namespaces(user=APIUser(id=user1.id), pagination=PaginationRequest(1, 100))
    assert len(nss) == 1
    assert user1.email
    assert nss[0].path.serialize() == user1.email.split("@")[0]
    nss, _ = await dm.syncer.group_repo.get_namespaces(user=APIUser(id=user2.id), pagination=PaginationRequest(1, 100))
    assert len(nss) == 1
    assert user2.email
    assert nss[0].path.serialize() == user2.email.split("@")[0]


@pytest.mark.asyncio
async def test_user_events_update(get_app_manager, admin_user: APIUser) -> None:
    kc_api = DummyKeycloakAPI()
    user1 = UserInfo(
        id="user-1-id",
        first_name="John",
        last_name="Doe",
        email="john.doe@gmail.com",
        namespace=UserNamespace(
            id=ULID(),
            created_by="user-1-id",
            underlying_resource_id="user-1-id",
            path=NamespacePath.from_strings("john.doe"),
        ),
    )
    assert admin_user.id
    admin_user_info = UserInfo(
        id=admin_user.id,
        first_name=admin_user.first_name,
        last_name=admin_user.last_name,
        email=admin_user.email,
        namespace=UserNamespace(
            id=ULID(),
            created_by=admin_user.id,
            underlying_resource_id=admin_user.id,
            path=NamespacePath.from_strings("admin-user"),
        ),
    )
    kc_api.users = get_kc_users([user1])
    dm = get_app_manager(kc_api)
    dm.kc_api = kc_api
    db_users = await dm.syncer.user_repo.get_users(admin_user)
    kc_users = [UserInfo.from_kc_user_payload(user) for user in dm.kc_api.get_users()]
    assert set(u.id for u in kc_users) == {user1.id}
    assert len(db_users) == 1  # listing users add the requesting user if not present
    await dm.syncer.users_sync(kc_api)
    db_users = await dm.syncer.user_repo.get_users(admin_user)
    kc_users.append(admin_user_info)
    assert set(u.id for u in kc_users) == set(u.id for u in db_users)
    # Add update and create events
    user2 = UserInfo(
        id="user-2-id",
        first_name="Jane",
        last_name="Doe",
        email="jane.doe@gmail.com",
        namespace=UserNamespace(
            id=ULID(),
            created_by="user-2-id",
            underlying_resource_id="user-2-id",
            path=NamespacePath.from_strings("jane.doe"),
        ),
    )
    user1_update = UserInfoFieldUpdate("user-1-id", datetime.utcnow(), "first_name", "Johnathan")
    user1_updated = UserInfo(**{**asdict(user1), "first_name": "Johnathan"})
    kc_api.user_events = get_kc_user_create_events([user2]) + get_kc_user_update_events([user1_update])
    # Process events and check if updates show up
    await dm.syncer.events_sync(kc_api)
    db_users = await dm.syncer.user_repo.get_users(admin_user)
    assert set(u.id for u in db_users) == set(u.id for u in [user1_updated, user2, admin_user_info])
    # Ensure re-processing events does not break anything
    kc_api.user_events = get_kc_user_create_events([user2]) + get_kc_user_update_events([user1_update])
    await dm.syncer.events_sync(kc_api)
    db_users = await dm.syncer.user_repo.get_users(admin_user)
    assert set(u.id for u in db_users) == set(u.id for u in [user1_updated, user2, admin_user_info])
    # Make sure that the addition of the user resulted in the creation of namespaces
    nss, _ = await dm.syncer.group_repo.get_namespaces(user=APIUser(id=user2.id), pagination=PaginationRequest(1, 100))
    assert len(nss) == 1
    assert user2.email
    assert nss[0].path.serialize() == user2.email.split("@")[0]


@pytest.mark.asyncio
async def test_admin_events(get_app_manager, admin_user: APIUser) -> None:
    kc_api = DummyKeycloakAPI()
    user1 = UserInfo(
        id="user-1-id",
        first_name="John",
        last_name="Doe",
        email="john.doe@gmail.com",
        namespace=UserNamespace(
            id=ULID(),
            created_by="user-1-id",
            underlying_resource_id="user-1-id",
            path=NamespacePath.from_strings("john.doe"),
        ),
    )
    user2 = UserInfo(
        id="user-2-id",
        first_name="Jane",
        last_name="Doe",
        email="jane.doe@gmail.com",
        namespace=UserNamespace(
            id=ULID(),
            created_by="user-2-id",
            underlying_resource_id="user-2-id",
            path=NamespacePath.from_strings("jane.doe"),
        ),
    )
    assert admin_user.id
    admin_user_info = UserInfo(
        id=admin_user.id,
        first_name=admin_user.first_name,
        last_name=admin_user.last_name,
        email=admin_user.email,
        namespace=UserNamespace(
            id=ULID(),
            created_by=admin_user.id,
            underlying_resource_id=admin_user.id,
            path=NamespacePath.from_strings("admin-user"),
        ),
    )
    kc_api.users = get_kc_users([user1, user2, admin_user_info])
    dm = get_app_manager(kc_api)
    dm.kc_api = kc_api
    db_users = await dm.syncer.user_repo.get_users(admin_user)
    kc_users = [UserInfo.from_kc_user_payload(user) for user in dm.kc_api.get_users()]
    assert set(u.id for u in kc_users) == set(u.id for u in [user1, user2, admin_user_info])
    assert len(db_users) == 1  # listing users add the requesting user if not present
    await dm.syncer.users_sync(kc_api)
    # Make sure that the addition of the users resulted in the creation of namespaces
    nss, _ = await dm.syncer.group_repo.get_namespaces(user=APIUser(id=user2.id), pagination=PaginationRequest(1, 100))
    assert len(nss) == 1
    assert user2.email
    assert nss[0].path.serialize() == user2.email.split("@")[0]
    db_users = await dm.syncer.user_repo.get_users(admin_user)
    assert set(u.id for u in kc_users) == set(u.id for u in db_users)
    # Add admin events
    user1_updated = UserInfo(**{**asdict(user1), "last_name": "Renku"})
    kc_api.admin_events = get_kc_admin_events(
        [(user2, KeycloakAdminEvent.DELETE), (user1_updated, KeycloakAdminEvent.UPDATE)]
    )
    # Process admin events
    await dm.syncer.events_sync(kc_api)
    db_users = await dm.syncer.user_repo.get_users(admin_user)
    assert set(u.id for u in [user1_updated, admin_user_info]) == set(u.id for u in db_users)
    # Make sure that the removal of a user removes the namespace
    nss, _ = await dm.syncer.group_repo.get_namespaces(user=APIUser(id=user2.id), pagination=PaginationRequest(1, 100))
    assert len(nss) == 0


@pytest.mark.asyncio
async def test_events_update_error(get_app_manager, admin_user: APIUser) -> None:
    kc_api = DummyKeycloakAPI()
    user1 = UserInfo(
        id="user-1-id",
        first_name="John",
        last_name="Doe",
        email="john.doe@gmail.com",
        namespace=UserNamespace(
            id=ULID(),
            created_by="user-1-id",
            underlying_resource_id="user-1-id",
            path=NamespacePath.from_strings("john.doe"),
        ),
    )
    user2 = UserInfo(
        id="user-2-id",
        first_name="Jane",
        last_name="Doe",
        email="jane.doe@gmail.com",
        namespace=UserNamespace(
            id=ULID(),
            created_by="user-2-id",
            underlying_resource_id="user-2-id",
            path=NamespacePath.from_strings("jane.doe"),
        ),
    )
    assert admin_user.id
    admin_user_info = UserInfo(
        id=admin_user.id,
        first_name=admin_user.first_name,
        last_name=admin_user.last_name,
        email=admin_user.email,
        namespace=UserNamespace(
            id=ULID(),
            created_by=admin_user.id,
            underlying_resource_id=admin_user.id,
            path=NamespacePath.from_strings("admin-user"),
        ),
    )
    kc_api.users = get_kc_users([user1, user2])
    dm = get_app_manager(kc_api)
    dm.kc_api = kc_api
    db_users = await dm.syncer.user_repo.get_users(admin_user)
    kc_users = [UserInfo.from_kc_user_payload(user) for user in dm.kc_api.get_users()]
    kc_users.append(admin_user_info)
    assert set(u.id for u in kc_users) == set(u.id for u in [user1, user2, admin_user_info])
    assert len(db_users) == 1  # listing users add the requesting user if not present
    assert db_users[0].id == admin_user_info.id
    assert db_users[0].first_name == admin_user_info.first_name
    assert db_users[0].last_name == admin_user_info.last_name
    assert db_users[0].email == admin_user_info.email
    await dm.syncer.users_sync(kc_api)
    db_users = await dm.syncer.user_repo.get_users(admin_user)
    assert set(u.id for u in kc_users) == set(u.id for u in db_users)
    # Add admin events
    user1_updated = UserInfo(**{**asdict(user1), "last_name": "Renku"})
    user2_updated = UserInfo(**{**asdict(user2), "last_name": "Smith"})
    kc_api.admin_events = (
        get_kc_admin_events([(user1_updated, KeycloakAdminEvent.UPDATE)])
        + [ValueError("Some random error in calling keycloak API")]
        + get_kc_admin_events([(user2_updated, KeycloakAdminEvent.UPDATE)])
    )
    # Process admin events
    with pytest.raises(ValueError):
        await dm.syncer.events_sync(kc_api)
    db_users = await dm.syncer.user_repo.get_users(admin_user)
    # An error occurs in processing an event or between events and none of the events are processed
    assert set(u.id for u in [user1, user2, admin_user_info]) == set(u.id for u in db_users)
    # Add admin events without error
    kc_api.admin_events = get_kc_admin_events([(user1_updated, KeycloakAdminEvent.UPDATE)]) + get_kc_admin_events(
        [(user2_updated, KeycloakAdminEvent.UPDATE)]
    )
    await dm.syncer.events_sync(kc_api)
    db_users = await dm.syncer.user_repo.get_users(admin_user)
    assert set(u.id for u in [user1_updated, user2_updated, admin_user_info]) == set(u.id for u in db_users)


@pytest.mark.asyncio
async def test_removing_non_existent_user(get_app_manager, admin_user: APIUser) -> None:
    kc_api = DummyKeycloakAPI()
    user1 = UserInfo(
        id="user-1-id",
        first_name="John",
        last_name="Doe",
        email="john.doe@gmail.com",
        namespace=UserNamespace(
            id=ULID(),
            created_by="user-1-id",
            underlying_resource_id="user-1-id",
            path=NamespacePath.from_strings("john.doe"),
        ),
    )
    non_existent_user = UserInfo(
        id="non-existent-id",
        first_name="Not",
        last_name="Exist",
        email="not.exist@gmail.com",
        namespace=UserNamespace(
            id=ULID(),
            created_by="noone",
            underlying_resource_id="non-existent-id",
            path=NamespacePath.from_strings("not.exist"),
        ),
    )
    assert admin_user.id
    admin_user_info = UserInfo(
        id=admin_user.id,
        first_name=admin_user.first_name,
        last_name=admin_user.last_name,
        email=admin_user.email,
        namespace=UserNamespace(
            id=ULID(),
            created_by=admin_user.id,
            underlying_resource_id=admin_user.id,
            path=NamespacePath.from_strings("admin-user"),
        ),
    )
    kc_api.users = get_kc_users([user1, admin_user_info])
    dm = get_app_manager(kc_api)
    dm.kc_api = kc_api
    db_users = await dm.syncer.user_repo.get_users(admin_user)
    kc_users = [UserInfo.from_kc_user_payload(user) for user in dm.kc_api.get_users()]
    assert set(u.id for u in kc_users) == set(u.id for u in [user1, admin_user_info])
    assert len(db_users) == 1
    await dm.syncer.users_sync(kc_api)
    db_users = await dm.syncer.user_repo.get_users(admin_user)
    assert set(u.id for u in kc_users) == set(u.id for u in db_users)
    # Add admin events
    kc_api.admin_events = get_kc_admin_events([(non_existent_user, KeycloakAdminEvent.DELETE)])
    # Process events
    await dm.syncer.events_sync(kc_api)
    db_users = await dm.syncer.user_repo.get_users(admin_user)
    assert set(u.id for u in db_users) == set(u.id for u in [user1, admin_user_info])


@pytest.mark.asyncio
async def test_avoiding_namespace_slug_duplicates(
    get_app_manager: Callable[..., DependencyManager], admin_user: APIUser
) -> None:
    kc_api = DummyKeycloakAPI()
    num_users = 10
    users = [
        UserInfo(
            id=f"user-{i}-id",
            first_name="John",
            last_name="Doe",
            email="john.doe@gmail.com",
            namespace=UserNamespace(
                id=ULID(),
                created_by=f"user-{i}-id",
                underlying_resource_id=f"user-{i}-id",
                path=NamespacePath.from_strings("john.doe"),
            ),
        )
        for i in range(1, num_users + 1)
    ]
    assert admin_user.id
    admin_user_info = UserInfo(
        id=admin_user.id,
        first_name=admin_user.first_name,
        last_name=admin_user.last_name,
        email=admin_user.email,
        namespace=UserNamespace(
            id=ULID(),
            created_by=admin_user.id,
            underlying_resource_id=admin_user.id,
            path=NamespacePath.from_strings("admin"),
        ),
    )
    kc_api.users = get_kc_users(users + [admin_user_info])
    dm = get_app_manager(kc_api)
    dm.kc_api = kc_api
    original_count = 0
    enumerated_count = 0
    random_count = 0
    await dm.syncer.users_sync(kc_api)
    for user in users:
        api_user = APIUser(id=user.id)
        nss, _ = await dm.syncer.group_repo.get_namespaces(api_user, PaginationRequest(1, 100))
        assert len(nss) == 1
        ns = nss[0]
        assert user.email
        prefix = user.email.split("@")[0]
        if re.match(rf"^{re.escape(prefix)}-[a-z0-9]{{8}}$", ns.path.serialize()):
            random_count += 1
        elif re.match(rf"^{re.escape(prefix)}-[1-5]$", ns.path.serialize()):
            enumerated_count += 1
        elif ns.path.serialize() == prefix:
            original_count += 1
    assert original_count == 1
    assert enumerated_count == 5
    assert random_count == num_users - enumerated_count - original_count


@pytest.mark.asyncio
async def test_authz_admin_sync(get_app_manager, admin_user: APIUser) -> None:
    kc_api = DummyKeycloakAPI()
    user1 = UserInfo(
        id="user-1-id",
        first_name="John",
        last_name="Doe",
        email="john.doe@gmail.com",
        namespace=UserNamespace(
            id=ULID(),
            created_by="user-1-id",
            underlying_resource_id="user-1-id",
            path=NamespacePath.from_strings("john.doe"),
        ),
    )
    assert admin_user.id
    admin_user_info = UserInfo(
        id=admin_user.id,
        first_name=admin_user.first_name,
        last_name=admin_user.last_name,
        email=admin_user.email,
        namespace=UserNamespace(
            id=ULID(),
            created_by=admin_user.id,
            underlying_resource_id=admin_user.id,
            path=NamespacePath.from_strings("admin-user"),
        ),
    )
    kc_api.users = get_kc_users([user1, admin_user_info])
    kc_api.user_roles = {admin_user_info.id: ["renku-admin"]}
    dm = get_app_manager(kc_api)
    dm.kc_api = kc_api
    db_users = await dm.syncer.user_repo.get_users(admin_user)
    kc_users = [UserInfo.from_kc_user_payload(user) for user in dm.kc_api.get_users()]
    await dm.syncer.users_sync(kc_api)
    await sync_admins_from_keycloak(kc_api, dm.authz)
    db_users = await dm.syncer.user_repo.get_users(admin_user)
    assert set(u.id for u in kc_users) == set(u.id for u in db_users)
    authz_admin_ids = await dm.authz._get_admin_user_ids()
    assert set(authz_admin_ids) == {admin_user_info.id}
    # Make user1 admin
    kc_api.user_roles[user1.id] = ["renku-admin"]
    await sync_admins_from_keycloak(kc_api, dm.authz)
    authz_admin_ids = await dm.authz._get_admin_user_ids()
    assert set(authz_admin_ids) == {admin_user_info.id, user1.id}
    # Remove original admin
    kc_api.user_roles.pop(admin_user_info.id)
    await sync_admins_from_keycloak(kc_api, dm.authz)
    authz_admin_ids = await dm.authz._get_admin_user_ids()
    assert set(authz_admin_ids) == {user1.id}


async def get_user_namespace_ids_in_authz(authz: Authz) -> set[str]:
    """Returns the user"""
    res = authz.client.ReadRelationships(
        ReadRelationshipsRequest(
            consistency=Consistency(fully_consistent=True),
            relationship_filter=RelationshipFilter(
                resource_type=ResourceType.user_namespace.value, optional_relation=_Relation.owner.value
            ),
        )
    )
    ids = [i.relationship.resource.object_id async for i in res]
    return set(ids)


@pytest.mark.asyncio
async def test_bootstraping_user_namespaces(get_app_manager, admin_user: APIUser):
    kc_api = DummyKeycloakAPI()
    user1 = UserInfo(
        id="user-1-id",
        first_name="John",
        last_name="Doe",
        email="john.doe@gmail.com",
        namespace=UserNamespace(
            id=ULID(),
            created_by="user-1-id",
            underlying_resource_id="user-1-id",
            path=NamespacePath.from_strings("john.doe"),
        ),
    )
    user2 = UserInfo(
        id="user-2-id",
        first_name="Jane",
        last_name="Doe",
        email="jane.doe@gmail.com",
        namespace=UserNamespace(
            id=ULID(),
            created_by="user-2-id",
            underlying_resource_id="user-2-id",
            path=NamespacePath.from_strings("jane.doe"),
        ),
    )
    assert admin_user.id
    kc_api.users = get_kc_users([user1, user2])
    dm = get_app_manager(kc_api)
    dm.kc_api = kc_api
    db_user_namespace_ids: set[ULID] = set()
    async with dm.config.db.async_session_maker() as session, session.begin():
        for user in [user1, user2]:
            user_orm = UserORM(
                user.id,
                first_name=user.first_name,
                last_name=user.last_name,
                email=user.email,
                namespace=NamespaceORM(user.id, user_id=user.id),
            )
            session.add(user_orm)
            await session.flush()
            db_user_namespace_ids.add(user_orm.namespace.id)
    authz_user_namespace_ids = await get_user_namespace_ids_in_authz(dm.authz)
    assert len(authz_user_namespace_ids) == 0
    await bootstrap_user_namespaces(dm)
    authz_user_namespace_ids = await get_user_namespace_ids_in_authz(dm.authz)
    assert db_user_namespace_ids == authz_user_namespace_ids


@pytest.mark.asyncio
async def test_fixing_project_group_namespace_relations(
    get_app_manager: Callable[..., DependencyManager], admin_user: APIUser
):
    admin_user_info = UserInfo(
        id=admin_user.id,
        first_name=admin_user.first_name,
        last_name=admin_user.last_name,
        email=admin_user.email,
        namespace=UserNamespace(
            id=ULID(),
            created_by=admin_user.id,
            underlying_resource_id=admin_user.id,
            path=NamespacePath.from_strings("admin-user"),
        ),
    )
    user1 = UserInfo(
        id="user-1-id",
        first_name="John",
        last_name="Doe",
        email="john.doe@gmail.com",
        namespace=UserNamespace(
            id=ULID(),
            created_by="user-1-id",
            underlying_resource_id="user-1-id",
            path=NamespacePath.from_strings("john.doe"),
        ),
    )
    user2 = UserInfo(
        id="user-2-id",
        first_name="Jane",
        last_name="Doe",
        email="jane.doe@gmail.com",
        namespace=UserNamespace(
            id=ULID(),
            created_by="user-2-id",
            underlying_resource_id="user-2-id",
            path=NamespacePath.from_strings("jane.doe"),
        ),
    )
    user1_api = APIUser(is_admin=False, id=user1.id, access_token="access_token")
    user2_api = APIUser(is_admin=False, id=user2.id, access_token="access_token")
    user_roles = {admin_user.id: get_kc_roles(["renku-admin"])}
    kc_api = DummyKeycloakAPI(users=get_kc_users([admin_user_info, user1, user2]), user_roles=user_roles)
    dm = get_app_manager(kc_api)
    dm.kc_api = kc_api
    # Sync users
    await dm.syncer.users_sync(kc_api)
    # Create group
    group_payload = GroupPostRequest(name="group1", slug="group1", description=None)
    group = await dm.group_repo.insert_group(user1_api, group_payload)
    # Create project
    project_payload = UnsavedProject(
        name="project1", slug="project1", namespace="group1", created_by=user1.id, visibility="private"
    )
    project = await dm.project_repo.insert_project(user1_api, project_payload)
    # Write the wrong group ID
    await dm.authz.client.WriteRelationships(
        WriteRelationshipsRequest(
            updates=[
                RelationshipUpdate(
                    operation=RelationshipUpdate.OPERATION_DELETE,
                    relationship=Relationship(
                        resource=_AuthzConverter.project(project.id),
                        relation=_Relation.project_namespace.value,
                        subject=SubjectReference(object=_AuthzConverter.group(group.id)),
                    ),
                ),
                RelationshipUpdate(
                    operation=RelationshipUpdate.OPERATION_TOUCH,
                    relationship=Relationship(
                        resource=_AuthzConverter.project(project.id),
                        relation=_Relation.project_namespace.value,
                        subject=SubjectReference(object=_AuthzConverter.group("random")),
                    ),
                ),
            ]
        )
    )
    # Add group member
    await dm.group_repo.update_group_members(user1_api, Slug("group1"), [UnsavedMember(Role.VIEWER, user2.id)])
    with pytest.raises(errors.MissingResourceError):
        await dm.project_repo.get_project(user2_api, project.id)
    await fix_mismatched_project_namespace_ids(dm)
    # After the fix you can read the project
    await dm.project_repo.get_project(user2_api, project.id)


@pytest.mark.asyncio
async def test_migrate_groups_make_all_public(get_app_manager: Callable[..., DependencyManager], admin_user: APIUser):
    admin_user_info = UserInfo(
        id=admin_user.id,
        first_name=admin_user.first_name,
        last_name=admin_user.last_name,
        email=admin_user.email,
        namespace=UserNamespace(
            id=ULID(),
            created_by=admin_user.id,
            underlying_resource_id=admin_user.id,
            path=NamespacePath.from_strings("admin-user"),
        ),
    )
    user = UserInfo(
        id="user-1-id",
        first_name="John",
        last_name="Doe",
        email="john.doe@gmail.com",
        namespace=UserNamespace(
            id=ULID(),
            created_by="user-1-id",
            underlying_resource_id="user-1-id",
            path=NamespacePath.from_strings("john.doe"),
        ),
    )
    user_api = APIUser(is_admin=False, id=user.id, access_token="access_token")
    anon_user_api = APIUser(is_admin=False)
    user_roles = {admin_user.id: get_kc_roles(["renku-admin"])}
    kc_api = DummyKeycloakAPI(users=get_kc_users([admin_user_info, user]), user_roles=user_roles)
    dm = get_app_manager(kc_api)
    dm.kc_api = kc_api
    # Sync users
    await dm.syncer.users_sync(kc_api)
    # Create group
    group_payload = GroupPostRequest(name="group1", slug="group1", description=None)
    group = await dm.group_repo.insert_group(user_api, group_payload)
    # Remove the public viewer relations
    await dm.authz.client.DeleteRelationships(
        DeleteRelationshipsRequest(
            relationship_filter=RelationshipFilter(
                resource_type=ResourceType.group.value, optional_relation=_Relation.public_viewer.value
            )
        ),
    )

    with pytest.raises(errors.MissingResourceError):
        group_members = await dm.group_repo.get_group_members(user=anon_user_api, slug=Slug(group.slug))

    await migrate_groups_make_all_public(dm)

    # After the migration, the group is public
    group_members = await dm.group_repo.get_group_members(user=anon_user_api, slug=Slug(group.slug))
    assert len(group_members) == 1
    assert group_members[0].id == "user-1-id"
    assert group_members[0].role.value == "owner"


@pytest.mark.asyncio
async def test_migrate_user_namespaces_make_all_public(
    get_app_manager: Callable[..., DependencyManager], admin_user: APIUser
):
    admin_user_info = UserInfo(
        id=admin_user.id,
        first_name=admin_user.first_name,
        last_name=admin_user.last_name,
        email=admin_user.email,
        namespace=UserNamespace(
            id=ULID(),
            created_by=admin_user.id,
            underlying_resource_id=admin_user.id,
            path=NamespacePath.from_strings("admin-user"),
        ),
    )
    user = UserInfo(
        id="user-1-id",
        first_name="John",
        last_name="Doe",
        email="john.doe@gmail.com",
        namespace=UserNamespace(
            id=ULID(),
            created_by="user-1-id",
            underlying_resource_id="user-1-id",
            path=NamespacePath.from_strings("john.doe"),
        ),
    )
    anon_user_api = APIUser(is_admin=False)
    user_roles = {admin_user.id: get_kc_roles(["renku-admin"])}
    kc_api = DummyKeycloakAPI(users=get_kc_users([admin_user_info, user]), user_roles=user_roles)
    dm = get_app_manager(kc_api)
    dm.kc_api = kc_api
    # Sync users
    await dm.syncer.users_sync(kc_api)
    # Remove the public viewer relations
    await dm.authz.client.DeleteRelationships(
        DeleteRelationshipsRequest(
            relationship_filter=RelationshipFilter(
                resource_type=ResourceType.user_namespace.value, optional_relation=_Relation.public_viewer.value
            )
        ),
    )

    with pytest.raises(errors.MissingResourceError):
        await dm.group_repo.get_namespace_by_slug(user=anon_user_api, slug=Slug("john.doe"))

    await migrate_user_namespaces_make_all_public(dm)

    # After the migration, the user namespace is public
    ns = await dm.group_repo.get_namespace_by_slug(user=anon_user_api, slug=Slug("john.doe"))
    assert ns.path.serialize() == "john.doe"
    assert ns.kind.value == "user"
    assert ns.created_by == user.id
