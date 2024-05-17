import json
from test.bases.renku_data_services.background_jobs.test_sync import get_kc_users
from typing import Any

import pytest
import pytest_asyncio
from authzed.api.v1 import Relationship, RelationshipUpdate, SubjectReference, WriteRelationshipsRequest
from sanic import Sanic
from sanic_testing.testing import SanicASGITestClient

from components.renku_data_services.utils.middleware import validate_null_byte
from renku_data_services.app_config.config import Config
from renku_data_services.authz.authz import _AuthzConverter
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
def member_1_user() -> UserInfo:
    return UserInfo("member-1", "Member-1", "Doe", "member-1.doe@gmail.com")


@pytest.fixture
def member_2_user() -> UserInfo:
    return UserInfo("member-2", "Member-2", "Doe", "member-2.doe@gmail.com")


@pytest.fixture
def users(admin_user, regular_user, member_1_user, member_2_user) -> list[UserInfo]:
    return [
        admin_user,
        regular_user,
        member_1_user,
        member_2_user,
    ]


@pytest.fixture
def admin_headers(admin_user: UserInfo) -> dict[str, str]:
    """Authentication headers for an admin user."""
    access_token = json.dumps(
        {"is_admin": True, "id": admin_user.id, "name": f"{admin_user.first_name} {admin_user.last_name}"}
    )
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
def user_headers(regular_user: UserInfo) -> dict[str, str]:
    """Authentication headers for a normal user."""
    access_token = json.dumps(
        {"is_admin": False, "id": regular_user.id, "name": f"{regular_user.first_name} {regular_user.last_name}"}
    )
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
def member_1_headers(member_1_user: UserInfo) -> dict[str, str]:
    """Authentication headers for a normal user."""
    access_token = json.dumps(
        {"is_admin": False, "id": member_1_user.id, "name": f"{member_1_user.first_name} {member_1_user.last_name}"}
    )
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
def member_2_headers(member_2_user: UserInfo) -> dict[str, str]:
    """Authentication headers for a normal user."""
    access_token = json.dumps(
        {"is_admin": False, "id": member_2_user.id, "name": f"{member_2_user.first_name} {member_2_user.last_name}"}
    )
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
def unauthorized_headers() -> dict[str, str]:
    """Authentication headers for an anonymous user (did not log in)."""
    return {"Authorization": "Bearer {}"}


@pytest.fixture
def bootstrap_admins(app_config: Config, admin_user: UserInfo):
    authz = app_config.authz
    rels: list[RelationshipUpdate] = []
    sub = SubjectReference(object=_AuthzConverter.user(admin_user.id))
    rels.append(
        RelationshipUpdate(
            operation=RelationshipUpdate.OPERATION_TOUCH,
            relationship=Relationship(resource=_AuthzConverter.platform(), relation="admin", subject=sub),
        )
    )
    authz.client.WriteRelationships(WriteRelationshipsRequest(updates=rels))


@pytest_asyncio.fixture
async def sanic_app(app_config: Config, users: list[UserInfo], bootstrap_admins) -> Sanic:
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
