import json
from copy import deepcopy
from typing import Any

import pytest
import pytest_asyncio
from authzed.api.v1 import Relationship, RelationshipUpdate, SubjectReference, WriteRelationshipsRequest
from sanic import Sanic
from sanic_testing.testing import SanicASGITestClient
from ulid import ULID

from components.renku_data_services.utils.middleware import validate_null_byte
from renku_data_services.app_config.config import Config
from renku_data_services.authz.admin_sync import sync_admins_from_keycloak
from renku_data_services.authz.authz import _AuthzConverter
from renku_data_services.base_models import Slug
from renku_data_services.data_api.app import register_all_handlers
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.namespace.models import Namespace, NamespaceKind
from renku_data_services.secrets.config import Config as SecretsConfig
from renku_data_services.secrets_storage_api.app import register_all_handlers as register_secrets_handlers
from renku_data_services.storage.rclone import RCloneValidator
from renku_data_services.users.dummy_kc_api import DummyKeycloakAPI
from renku_data_services.users.models import UserInfo
from test.bases.renku_data_services.background_jobs.test_sync import get_kc_users


@pytest.fixture
def admin_user() -> UserInfo:
    return UserInfo(
        id="admin",
        first_name="Admin",
        last_name="Doe",
        email="admin.doe@gmail.com",
        namespace=Namespace(
            id=ULID(), slug="admin.doe", kind=NamespaceKind.user, underlying_resource_id="admin", created_by="admin"
        ),
    )


@pytest.fixture
def regular_user() -> UserInfo:
    return UserInfo(
        id="user",
        first_name="User",
        last_name="Doe",
        email="user.doe@gmail.com",
        namespace=Namespace(
            id=ULID(), slug="user.doe", kind=NamespaceKind.user, underlying_resource_id="user", created_by="user"
        ),
    )


@pytest.fixture
def member_1_user() -> UserInfo:
    return UserInfo(
        id="member-1",
        first_name="Member-1",
        last_name="Doe",
        email="member-1.doe@gmail.com",
        namespace=Namespace(
            id=ULID(),
            slug="member-1.doe",
            kind=NamespaceKind.user,
            underlying_resource_id="member-1",
            created_by="member-1",
        ),
    )


@pytest.fixture
def member_2_user() -> UserInfo:
    return UserInfo(
        id="member-2",
        first_name="Member-2",
        last_name="Doe",
        email="member-2.doe@gmail.com",
        namespace=Namespace(
            id=ULID(),
            slug="member-2.doe",
            kind=NamespaceKind.user,
            underlying_resource_id="member-2",
            created_by="member-2",
        ),
    )


@pytest.fixture
def project_members(member_1_user: UserInfo, member_2_user: UserInfo) -> list[dict[str, str]]:
    """List of a project's members."""
    return [{"id": member_1_user.id, "role": "viewer"}, {"id": member_2_user.id, "role": "owner"}]


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
        {
            "is_admin": True,
            "id": admin_user.id,
            "name": f"{admin_user.first_name} {admin_user.last_name}",
            "first_name": admin_user.first_name,
            "last_name": admin_user.last_name,
            "email": admin_user.email,
            "full_name": f"{admin_user.first_name} {admin_user.last_name}",
        }
    )
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
def user_headers(regular_user: UserInfo) -> dict[str, str]:
    """Authentication headers for a normal user."""
    access_token = json.dumps(
        {
            "is_admin": False,
            "id": regular_user.id,
            "name": f"{regular_user.first_name} {regular_user.last_name}",
            "first_name": regular_user.first_name,
            "last_name": regular_user.last_name,
            "email": regular_user.email,
            "full_name": f"{regular_user.first_name} {regular_user.last_name}",
        }
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
def bootstrap_admins(app_config: Config, admin_user: UserInfo) -> None:
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
async def sanic_app_no_migrations(
    app_config: Config, users: list[UserInfo], bootstrap_admins, admin_user: UserInfo
) -> Sanic:
    app_config.kc_api = DummyKeycloakAPI(users=get_kc_users(users), user_roles={admin_user.id: ["renku-admin"]})
    app = Sanic(app_config.app_name)
    app = register_all_handlers(app, app_config)
    app.register_middleware(validate_null_byte, "request")
    validator = RCloneValidator()
    app.ext.dependency(validator)
    return app


@pytest_asyncio.fixture
async def sanic_client_no_migrations(sanic_app_no_migrations: Sanic) -> SanicASGITestClient:
    return SanicASGITestClient(sanic_app_no_migrations)


@pytest_asyncio.fixture
async def sanic_app(sanic_app_no_migrations: Sanic, app_config: Config) -> Sanic:
    run_migrations_for_app("common")
    await app_config.kc_user_repo.initialize(app_config.kc_api)
    await sync_admins_from_keycloak(app_config.kc_api, app_config.authz)
    await app_config.group_repo.generate_user_namespaces()
    return sanic_app_no_migrations


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
        if "name" not in payload:
            payload.update({"name": name})
        if "namespace" not in payload:
            payload.update({"namespace": f"{user.first_name}.{user.last_name}".lower()})

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


@pytest.fixture
def create_group(sanic_client, user_headers, admin_headers):
    async def create_group_helper(
        name: str, admin: bool = False, members: list[dict[str, str]] = None, **payload
    ) -> dict[str, Any]:
        headers = admin_headers if admin else user_headers
        group_payload = {"slug": Slug.from_name(name).value}
        group_payload.update(payload)
        group_payload.update({"name": name})

        _, response = await sanic_client.post("/api/data/groups", headers=headers, json=group_payload)

        assert response.status_code == 201, response.text
        group = response.json

        if members:
            _, response = await sanic_client.patch(
                f"/api/data/groups/{group['slug']}/members", headers=headers, json=members
            )

            assert response.status_code == 200, response.text

        return group

    return create_group_helper


@pytest.fixture
def create_resource_pool(sanic_client, user_headers, admin_headers):
    async def create_resource_pool_helper(admin: bool = False, **payload) -> dict[str, Any]:
        headers = admin_headers if admin else user_headers
        payload = payload.copy()
        _, res = await sanic_client.post("/api/data/resource_pools", headers=headers, json=payload)
        assert res.status_code == 201, res.text
        assert res.json is not None
        return res.json

    return create_resource_pool_helper


_valid_resource_pool_payload: dict[str, Any] = {
    "name": "test-name",
    "classes": [
        {
            "cpu": 1.0,
            "memory": 10,
            "gpu": 0,
            "name": "test-class-name",
            "max_storage": 100,
            "default_storage": 1,
            "default": True,
            "node_affinities": [],
            "tolerations": [],
        }
    ],
    "quota": {"cpu": 100, "memory": 100, "gpu": 0},
    "default": False,
    "public": True,
    "idle_threshold": 86400,
    "hibernation_threshold": 99999,
}


@pytest.fixture
def valid_resource_pool_payload() -> dict[str, Any]:
    return deepcopy(_valid_resource_pool_payload)


@pytest.fixture
def valid_resource_class_payload() -> dict[str, Any]:
    return deepcopy(_valid_resource_pool_payload["classes"][0])


@pytest_asyncio.fixture
async def secrets_sanic_client(secrets_storage_app_config: SecretsConfig, users: list[UserInfo]) -> SanicASGITestClient:
    app = Sanic(secrets_storage_app_config.app_name)
    app = register_secrets_handlers(app, secrets_storage_app_config)
    return SanicASGITestClient(app)
