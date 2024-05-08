import json
import re
import secrets
from collections.abc import Callable, Generator
from dataclasses import asdict
from datetime import datetime
from typing import Any

import pytest

from bases.renku_data_services.keycloak_sync.config import SyncConfig
from renku_data_services.base_api.pagination import PaginationRequest
from renku_data_services.base_models import APIUser
from renku_data_services.db_config import DBConfig
from renku_data_services.message_queue.config import RedisConfig
from renku_data_services.message_queue.db import EventRepository
from renku_data_services.message_queue.redis_queue import RedisQueue
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.users.db import UserRepo, UsersSync
from renku_data_services.users.dummy_kc_api import DummyKeycloakAPI
from renku_data_services.users.models import KeycloakAdminEvent, UserInfo, UserInfoUpdate


@pytest.fixture
def db_config(postgresql, monkeypatch) -> Generator[Any, Any, SyncConfig]:
    monkeypatch.setenv("DB_NAME", postgresql.info.dbname)
    db_config = DBConfig.from_env()
    monkeypatch.delenv("DB_NAME", raising=False)

    yield db_config
    monkeypatch.delenv("DB_NAME", raising=False)
    # NOTE: This is necessary because the postgresql pytest extension does not close
    # the async connection/pool we use in the config and the connection will succeed in the first
    # test but fail in all others if the connection is not disposed at the end of every test.
    db_config.dispose_connection()


@pytest.fixture
def get_app_configs(db_config: DBConfig):
    def _get_app_configs(kc_api: DummyKeycloakAPI, total_user_sync: bool = False) -> tuple[SyncConfig, UserRepo]:
        redis = RedisConfig.fake()
        message_queue = RedisQueue(redis)
        event_repo = EventRepository(db_config.async_session_maker, message_queue=message_queue)
        group_repo = GroupRepository(db_config.async_session_maker)
        users_sync = UsersSync(
            db_config.async_session_maker,
            message_queue=message_queue,
            event_repo=event_repo,
            group_repo=group_repo,
        )
        config = SyncConfig(syncer=users_sync, kc_api=kc_api, total_user_sync=total_user_sync)
        user_repo = UserRepo(
            db_config.async_session_maker,
            message_queue=message_queue,
            event_repo=event_repo,
            group_repo=group_repo,
            encryption_key=secrets.token_bytes(32),
        )
        return config, user_repo

    yield _get_app_configs


def get_kc_users(updates: list[UserInfo]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for update in updates:
        output.append(update._to_keycloak_dict())
    return output


def get_kc_user_update_events(updates: list[UserInfoUpdate]) -> list[dict[str, Any]]:
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


@pytest.mark.asyncio
async def test_total_users_sync(get_app_configs: Callable[..., tuple[SyncConfig, UserRepo]], admin_user: APIUser):
    kc_api = DummyKeycloakAPI()
    user1 = UserInfo("user-1-id", "John", "Doe", "john.doe@gmail.com")
    user2 = UserInfo("user-2-id", "Jane", "Doe", "jane.doe@gmail.com")
    assert admin_user.id
    admin_user_info = UserInfo(
        id=admin_user.id,
        first_name=admin_user.first_name,
        last_name=admin_user.last_name,
        email=admin_user.email,
    )
    kc_api.users = get_kc_users([user1, user2, admin_user_info])
    sync_config: SyncConfig
    user_repo: UserRepo
    sync_config, user_repo = get_app_configs(kc_api)
    db_users = await user_repo.get_users(admin_user)
    kc_users = [UserInfo.from_kc_user_payload(user) for user in sync_config.kc_api.get_users()]
    kc_users.append(
        UserInfo(
            id=admin_user.id,
            first_name=admin_user.first_name,
            last_name=admin_user.last_name,
            email=admin_user.email,
        )
    )
    assert set(kc_users) == {user1, user2, admin_user_info}
    assert len(db_users) == 1  # listing users add the requesting user if not present
    await sync_config.syncer.users_sync(kc_api)
    db_users = await user_repo.get_users(admin_user)
    assert set(kc_users) == set(db_users)
    # Make sure doing users sync again does not change anything and works
    await sync_config.syncer.users_sync(kc_api)
    db_users = await user_repo.get_users(admin_user)
    assert set(kc_users) == set(db_users)
    # Make sure that the addition of the users resulted in the creation of namespaces
    nss, _ = await sync_config.syncer.group_repo.get_namespaces(
        user=APIUser(id=user1.id), pagination=PaginationRequest(1, 100)
    )
    assert len(nss) == 1
    assert user1.email
    assert nss[0].slug == user1.email.split("@")[0]
    nss, _ = await sync_config.syncer.group_repo.get_namespaces(
        user=APIUser(id=user2.id), pagination=PaginationRequest(1, 100)
    )
    assert len(nss) == 1
    assert user2.email
    assert nss[0].slug == user2.email.split("@")[0]


@pytest.mark.asyncio
async def test_user_events_update(get_app_configs, admin_user: APIUser):
    kc_api = DummyKeycloakAPI()
    user1 = UserInfo("user-1-id", "John", "Doe", "john.doe@gmail.com")
    assert admin_user.id
    admin_user_info = UserInfo(
        id=admin_user.id,
        first_name=admin_user.first_name,
        last_name=admin_user.last_name,
        email=admin_user.email,
    )
    kc_api.users = get_kc_users([user1])
    sync_config: SyncConfig
    user_repo: UserRepo
    sync_config, user_repo = get_app_configs(kc_api)
    db_users = await user_repo.get_users(admin_user)
    kc_users = [UserInfo.from_kc_user_payload(user) for user in sync_config.kc_api.get_users()]
    assert set(kc_users) == {user1}
    assert len(db_users) == 1  # listing users add the requesting user if not present
    await sync_config.syncer.users_sync(kc_api)
    db_users = await user_repo.get_users(admin_user)
    kc_users.append(admin_user_info)
    assert set(kc_users) == set(db_users)
    # Add update and create events
    user2 = UserInfo("user-2-id", "Jane", "Doe", "jane.doe@gmail.com")
    user1_update = UserInfoUpdate("user-1-id", datetime.utcnow(), "first_name", "Johnathan")
    user1_updated = UserInfo(**{**asdict(user1), "first_name": "Johnathan"})
    kc_api.user_events = get_kc_user_create_events([user2]) + get_kc_user_update_events([user1_update])
    # Process events and check if updates show up
    await sync_config.syncer.events_sync(kc_api)
    db_users = await user_repo.get_users(admin_user)
    assert set(db_users) == {user1_updated, user2, admin_user_info}
    # Ensure re-processing events does not break anything
    kc_api.user_events = get_kc_user_create_events([user2]) + get_kc_user_update_events([user1_update])
    await sync_config.syncer.events_sync(kc_api)
    db_users = await user_repo.get_users(admin_user)
    assert set(db_users) == {user1_updated, user2, admin_user_info}
    # Make sure that the addition of the user resulted in the creation of namespaces
    nss, _ = await sync_config.syncer.group_repo.get_namespaces(
        user=APIUser(id=user2.id), pagination=PaginationRequest(1, 100)
    )
    assert len(nss) == 1
    assert user2.email
    assert nss[0].slug == user2.email.split("@")[0]


@pytest.mark.asyncio
async def test_admin_events(get_app_configs, admin_user: APIUser):
    kc_api = DummyKeycloakAPI()
    user1 = UserInfo("user-1-id", "John", "Doe", "john.doe@gmail.com")
    user2 = UserInfo("user-2-id", "Jane", "Doe", "jane.doe@gmail.com")
    assert admin_user.id
    admin_user_info = UserInfo(
        id=admin_user.id,
        first_name=admin_user.first_name,
        last_name=admin_user.last_name,
        email=admin_user.email,
    )
    kc_api.users = get_kc_users([user1, user2, admin_user_info])
    sync_config: SyncConfig
    user_repo: UserRepo
    sync_config, user_repo = get_app_configs(kc_api)
    db_users = await user_repo.get_users(admin_user)
    kc_users = [UserInfo.from_kc_user_payload(user) for user in sync_config.kc_api.get_users()]
    assert set(kc_users) == {user1, user2, admin_user_info}
    assert len(db_users) == 1  # listing users add the requesting user if not present
    await sync_config.syncer.users_sync(kc_api)
    # Make sure that the addition of the users resulted in the creation of namespaces
    nss, _ = await sync_config.syncer.group_repo.get_namespaces(
        user=APIUser(id=user2.id), pagination=PaginationRequest(1, 100)
    )
    assert len(nss) == 1
    assert user2.email
    assert nss[0].slug == user2.email.split("@")[0]
    db_users = await user_repo.get_users(admin_user)
    assert set(kc_users) == set(db_users)
    # Add admin events
    user1_updated = UserInfo(**{**asdict(user1), "last_name": "Renku"})
    kc_api.admin_delete_events = get_kc_admin_events([(user2, KeycloakAdminEvent.DELETE)])
    kc_api.admin_update_events = get_kc_admin_events([(user1_updated, KeycloakAdminEvent.UPDATE)])
    # Process admin events
    await sync_config.syncer.events_sync(kc_api)
    db_users = await user_repo.get_users(admin_user)
    assert {user1_updated, admin_user_info} == set(db_users)
    # Make sure that the removal of a user removes the namespace
    nss, _ = await sync_config.syncer.group_repo.get_namespaces(
        user=APIUser(id=user2.id), pagination=PaginationRequest(1, 100)
    )
    assert len(nss) == 0


@pytest.mark.asyncio
async def test_events_update_error(get_app_configs, admin_user: APIUser):
    kc_api = DummyKeycloakAPI()
    user1 = UserInfo("user-1-id", "John", "Doe", "john.doe@gmail.com")
    user2 = UserInfo("user-2-id", "Jane", "Doe", "jane.doe@gmail.com")
    assert admin_user.id
    admin_user_info = UserInfo(
        id=admin_user.id,
        first_name=admin_user.first_name,
        last_name=admin_user.last_name,
        email=admin_user.email,
    )
    kc_api.users = get_kc_users([user1, user2])
    sync_config: SyncConfig
    user_repo: UserRepo
    sync_config, user_repo = get_app_configs(kc_api)
    db_users = await user_repo.get_users(admin_user)
    kc_users = [UserInfo.from_kc_user_payload(user) for user in sync_config.kc_api.get_users()]
    kc_users.append(admin_user_info)
    assert set(kc_users) == {user1, user2, admin_user_info}
    assert len(db_users) == 1  # listing users add the requesting user if not present
    assert db_users[0] == admin_user_info
    await sync_config.syncer.users_sync(kc_api)
    db_users = await user_repo.get_users(admin_user)
    assert set(kc_users) == set(db_users)
    # Add admin events
    user1_updated = UserInfo(**{**asdict(user1), "last_name": "Renku"})
    user2_updated = UserInfo(**{**asdict(user2), "last_name": "Smith"})
    kc_api.admin_update_events = (
        get_kc_admin_events([(user1_updated, KeycloakAdminEvent.UPDATE)])
        + [ValueError("Some random error in calling keycloak API")]
        + get_kc_admin_events([(user2_updated, KeycloakAdminEvent.UPDATE)])
    )
    # Process admin events
    with pytest.raises(ValueError):
        await sync_config.syncer.events_sync(kc_api)
    db_users = await user_repo.get_users(admin_user)
    # An error occurs in processing an event or between events and none of the events are processed
    assert {user1, user2, admin_user_info} == set(db_users)
    # Add admin events without error
    kc_api.admin_update_events = get_kc_admin_events(
        [(user1_updated, KeycloakAdminEvent.UPDATE)]
    ) + get_kc_admin_events([(user2_updated, KeycloakAdminEvent.UPDATE)])
    await sync_config.syncer.events_sync(kc_api)
    db_users = await user_repo.get_users(admin_user)
    assert {user1_updated, user2_updated, admin_user_info} == set(db_users)


@pytest.mark.asyncio
async def test_removing_non_existent_user(get_app_configs, admin_user: APIUser):
    kc_api = DummyKeycloakAPI()
    user1 = UserInfo("user-1-id", "John", "Doe", "john.doe@gmail.com")
    non_existent_user = UserInfo("user-2-id", "Jane", "Doe", "jane.doe@gmail.com")
    assert admin_user.id
    admin_user_info = UserInfo(
        id=admin_user.id,
        first_name=admin_user.first_name,
        last_name=admin_user.last_name,
        email=admin_user.email,
    )
    kc_api.users = get_kc_users([user1, admin_user_info])
    sync_config: SyncConfig
    user_repo: UserRepo
    sync_config, user_repo = get_app_configs(kc_api)
    db_users = await user_repo.get_users(admin_user)
    kc_users = [UserInfo.from_kc_user_payload(user) for user in sync_config.kc_api.get_users()]
    assert set(kc_users) == {user1, admin_user_info}
    assert len(db_users) == 1
    await sync_config.syncer.users_sync(kc_api)
    db_users = await user_repo.get_users(admin_user)
    assert set(kc_users) == set(db_users)
    # Add admin events
    kc_api.admin_delete_events = get_kc_admin_events([(non_existent_user, KeycloakAdminEvent.UPDATE)])
    # Process events
    await sync_config.syncer.events_sync(kc_api)
    db_users = await user_repo.get_users(admin_user)
    assert set(db_users) == {user1, admin_user_info}


@pytest.mark.asyncio
async def test_avoiding_namespace_slug_duplicates(
    get_app_configs: Callable[..., tuple[SyncConfig, UserRepo]], admin_user: APIUser
):
    kc_api = DummyKeycloakAPI()
    num_users = 10
    users = [UserInfo(f"user-{i}-id", "John", "Doe", "john.doe@gmail.com") for i in range(1, num_users + 1)]
    assert admin_user.id
    admin_user_info = UserInfo(
        id=admin_user.id,
        first_name=admin_user.first_name,
        last_name=admin_user.last_name,
        email=admin_user.email,
    )
    kc_api.users = get_kc_users(users + [admin_user_info])
    sync_config, _ = get_app_configs(kc_api)
    original_count = 0
    enumerated_count = 0
    random_count = 0
    await sync_config.syncer.users_sync(kc_api)
    for user in users:
        api_user = APIUser(id=user.id)
        nss, _ = await sync_config.syncer.group_repo.get_namespaces(api_user, PaginationRequest(1, 100))
        assert len(nss) == 1
        ns = nss[0]
        assert user.email
        prefix = user.email.split("@")[0]
        if re.match(rf"^{re.escape(prefix)}-[a-z0-9]{{8}}$", ns.slug):
            random_count += 1
        elif re.match(rf"^{re.escape(prefix)}-[1-5]$", ns.slug):
            enumerated_count += 1
        elif ns.slug == prefix:
            original_count += 1
    assert original_count == 1
    assert enumerated_count == 5
    assert random_count == num_users - enumerated_count - original_count
