import json
from test.bases.renku_data_services.keycloak_sync.test_sync import get_kc_users
from typing import Any

import pytest
import pytest_asyncio
from sanic import Sanic
from sanic_testing.testing import SanicASGITestClient

from components.renku_data_services.utils.middleware import validate_null_byte
from renku_data_services.app_config.config import Config
from renku_data_services.data_api.app import register_all_handlers
from renku_data_services.secrets.config import Config as SecretsConfig
from renku_data_services.secrets_storage_api.app import register_all_handlers as register_secrets_handlers
from renku_data_services.storage.rclone import RCloneValidator
from renku_data_services.users.dummy_kc_api import DummyKeycloakAPI
from renku_data_services.users.models import UserInfo


@pytest.fixture
def admin_user() -> UserInfo:
    return UserInfo("admin", "Admin", "Doe", "admin.doe@gmail.com")


@pytest.fixture
def regular_user() -> UserInfo:
    return UserInfo("user", "User", "Doe", "user.doe@gmail.com")


@pytest.fixture
def project_normal_member() -> UserInfo:
    """A normal (non owner) project member."""
    return UserInfo("normal-member", "Normal", "Member", "normal.member@gmail.com")


@pytest.fixture
def project_owner_member() -> UserInfo:
    """A member and owner of a project."""
    return UserInfo("owner-member", "Owner", "Member", "owner.member@gmail.com")


@pytest.fixture
def project_non_member() -> UserInfo:
    """A user that isn't a member of a project."""
    return UserInfo("non-member", "Non", "Member", "non.member@gmail.com")


@pytest.fixture
def users(admin_user, regular_user, project_normal_member, project_owner_member, project_non_member) -> list[UserInfo]:
    return [
        admin_user,
        regular_user,
        UserInfo("member-1", "Member-1", "Doe", "member-1.doe@gmail.com"),
        UserInfo("member-2", "Member-2", "Doe", "member-2.doe@gmail.com"),
        project_normal_member,
        project_owner_member,
        project_non_member,
    ]


@pytest.fixture
def admin_headers() -> dict[str, str]:
    """Authentication headers for an admin user."""
    access_token = json.dumps({"is_admin": True, "id": "admin", "name": "Admin User"})
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
def user_headers() -> dict[str, str]:
    """Authentication headers for a normal user."""
    access_token = json.dumps({"is_admin": False, "id": "user", "name": "Normal User"})
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
def project_normal_member_headers(project_normal_member) -> dict[str, str]:
    """Authentication headers for a normal project member user."""
    access_token = json.dumps({"is_admin": False, "id": project_normal_member.id})
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
def project_owner_member_headers(project_owner_member) -> dict[str, str]:
    """Authentication headers for a normal project owner user."""
    access_token = json.dumps({"is_admin": False, "id": project_owner_member.id})
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
def project_non_member_headers(project_non_member) -> dict[str, str]:
    """Authentication headers for a user that isn't a member of a project."""
    access_token = json.dumps({"is_admin": False, "id": project_non_member.id})
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
def unauthorized_headers() -> dict[str, str]:
    """Authentication headers for an anonymous user (did not log in)."""
    return {"Authorization": "Bearer {}"}


@pytest.fixture
def project_members(project_normal_member, project_owner_member) -> list[dict[str, str]]:
    """List of a project's members."""
    return [{"id": project_normal_member.id, "role": "member"}, {"id": project_owner_member.id, "role": "owner"}]


@pytest_asyncio.fixture
async def sanic_app(app_config: Config, users: list[UserInfo]) -> Sanic:
    app_config.kc_api = DummyKeycloakAPI(users=get_kc_users(users))
    app = Sanic(app_config.app_name)
    app = register_all_handlers(app, app_config)
    app.register_middleware(validate_null_byte, "request")
    await app_config.kc_user_repo.initialize(app_config.kc_api)
    await app_config.group_repo.generate_user_namespaces()
    validator = RCloneValidator()
    app.ext.dependency(validator)
    return app


@pytest_asyncio.fixture
async def sanic_client(sanic_app: Sanic) -> SanicASGITestClient:
    return SanicASGITestClient(sanic_app)


@pytest.fixture
def create_project(sanic_client, user_headers, admin_headers, regular_user, admin_user):
    async def create_project_helper(
        name: str, admin: bool = False, members: list[dict[str, str]] = None, **payload
    ) -> dict[str, Any]:
        headers = admin_headers if admin else user_headers
        user = admin_user if admin else regular_user
        payload = payload.copy()
        payload.update({"name": name, "namespace": f"{user.first_name}.{user.last_name}"})

        _, response = await sanic_client.post("/api/data/projects", headers=headers, json=payload)

        assert response.status_code == 201, response.text
        project = response.json

        if members:
            _, response = await sanic_client.patch(
                f"/api/data/projects/{project['id']}/members", headers=headers, json=members
            )

            assert response.status_code == 200, response.text

        return project

    return create_project_helper


@pytest_asyncio.fixture
async def secrets_sanic_client(secrets_storage_app_config: SecretsConfig, users: list[UserInfo]) -> SanicASGITestClient:
    app = Sanic(secrets_storage_app_config.app_name)
    app = register_secrets_handlers(app, secrets_storage_app_config)
    return SanicASGITestClient(app)
