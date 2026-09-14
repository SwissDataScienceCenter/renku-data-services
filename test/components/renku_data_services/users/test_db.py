"""Tests for database users."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services.base_models.core import APIUser, AuthenticatedAPIUser
from renku_data_services.base_models.nel import Nel
from renku_data_services.errors import errors
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.users.db import DbUsernameResolver, SSHKeyRepository, UserRepo
from renku_data_services.users.models import UnsavedSSHKey, UserInfo


@dataclass
class UsernameResolver(DbUsernameResolver):
    session_maker: Callable[..., AsyncSession]

    def make_session(self) -> AsyncSession:
        return self.session_maker()


def _username(info: UserInfo) -> str:
    return info.namespace.path.first.value


@pytest.mark.asyncio
async def test_username_resolve(app_manager_instance) -> None:
    run_migrations_for_app("common")
    user_repo: UserRepo = app_manager_instance.kc_user_repo
    user1 = APIUser(id="id-123", first_name="Mads", last_name="Pedersen")
    user2 = APIUser(id="id-234", first_name="Wout", last_name="van Art")
    user_info1 = cast(UserInfo, await user_repo.get_or_create_user(user1, str(user1.id)))
    user_info2 = cast(UserInfo, await user_repo.get_or_create_user(user2, str(user2.id)))

    resolver = UsernameResolver(app_manager_instance.config.db.async_session_maker)
    data = await resolver.resolve_usernames(Nel.of("a.b", _username(user_info1), _username(user_info2)))
    assert data is not None
    assert data.get(_username(user_info1)) == user_info1.id
    assert data.get(_username(user_info2)) == user_info2.id
    assert len(data) == 2


async def _make_user(app_manager_instance) -> AuthenticatedAPIUser:
    user = AuthenticatedAPIUser(id=str(uuid.uuid4()), access_token="token")
    await app_manager_instance.kc_user_repo.get_or_create_user(user, user.id)
    return user


def _unsaved(fingerprint: str, name: str | None = None) -> UnsavedSSHKey:
    return UnsavedSSHKey(public_key="ssh-ed25519 AAAA", key_type="ssh-ed25519", fingerprint=fingerprint, name=name)


@pytest.mark.asyncio
async def test_ssh_key_repository_crud(app_manager_instance) -> None:
    run_migrations_for_app("common")
    user = await _make_user(app_manager_instance)
    repo = SSHKeyRepository(app_manager_instance.config.db.async_session_maker)

    created = await repo.insert_ssh_key(requested_by=user, ssh_key=_unsaved("fp1", "laptop"))
    assert created.fingerprint == "fp1"
    assert created.user_id == user.id

    assert [k.id for k in await repo.get_ssh_keys(requested_by=user)] == [created.id]
    assert (await repo.get_ssh_key(requested_by=user, key_id=created.id)).id == created.id
    assert await repo.get_user_id_by_fingerprint("fp1") == user.id
    assert await repo.get_user_id_by_fingerprint("does-not-exist") is None

    await repo.delete_ssh_key(requested_by=user, key_id=created.id)
    assert await repo.get_ssh_keys(requested_by=user) == []


@pytest.mark.asyncio
async def test_ssh_key_duplicate_fingerprint_conflicts(app_manager_instance) -> None:
    run_migrations_for_app("common")
    user_a = await _make_user(app_manager_instance)
    user_b = await _make_user(app_manager_instance)
    repo = SSHKeyRepository(app_manager_instance.config.db.async_session_maker)
    await repo.insert_ssh_key(requested_by=user_a, ssh_key=_unsaved("dup"))
    with pytest.raises(errors.ConflictError):
        await repo.insert_ssh_key(requested_by=user_a, ssh_key=_unsaved("dup"))
    # One fingerprint maps to exactly one user: a different user gets the same conflict.
    with pytest.raises(errors.ConflictError):
        await repo.insert_ssh_key(requested_by=user_b, ssh_key=_unsaved("dup"))


@pytest.mark.asyncio
async def test_ssh_key_scoped_to_owner(app_manager_instance) -> None:
    run_migrations_for_app("common")
    user_a = await _make_user(app_manager_instance)
    user_b = await _make_user(app_manager_instance)
    repo = SSHKeyRepository(app_manager_instance.config.db.async_session_maker)
    created = await repo.insert_ssh_key(requested_by=user_a, ssh_key=_unsaved("owner-fp"))

    assert await repo.get_ssh_keys(requested_by=user_b) == []
    with pytest.raises(errors.MissingResourceError):
        await repo.get_ssh_key(requested_by=user_b, key_id=created.id)
    await repo.delete_ssh_key(requested_by=user_b, key_id=created.id)
    assert [k.id for k in await repo.get_ssh_keys(requested_by=user_a)] == [created.id]
