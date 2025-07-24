"""Tests for database users."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services.base_models.core import APIUser
from renku_data_services.base_models.nel import Nel
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.users.db import DbUsernameResolver, UserRepo
from renku_data_services.users.models import UserInfo


@dataclass
class TestUsernameResolver(DbUsernameResolver):
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

    resolver = TestUsernameResolver(app_manager_instance.config.db.async_session_maker)
    data = await resolver.resolve_usernames(Nel.of("a.b", _username(user_info1), _username(user_info2)))
    assert data is not None
    assert data.get(_username(user_info1)) == user_info1.id
    assert data.get(_username(user_info2)) == user_info2.id
    assert len(data) == 2
