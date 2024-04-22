import json

from authzed.api.v1 import Relationship, RelationshipUpdate, SubjectReference, WriteRelationshipsRequest
from test.bases.renku_data_services.keycloak_sync.test_sync import get_kc_users

import pytest
import pytest_asyncio
from sanic import Sanic
from sanic_testing.testing import SanicASGITestClient

from components.renku_data_services.utils.middleware import validate_null_byte
from renku_data_services.app_config.config import Config
from renku_data_services.data_api.app import register_all_handlers
from renku_data_services.storage.rclone import RCloneValidator
from renku_data_services.users.dummy_kc_api import DummyKeycloakAPI
from renku_data_services.users.models import UserInfo
from renku_data_services.authz.authz import _AuthzConverter


@pytest.fixture
def admin_user() -> UserInfo:
    return UserInfo("admin", "Admin", "Doe", "admin.doe@gmail.com")


@pytest.fixture
def regular_user() -> UserInfo:
    return UserInfo("user", "User", "Doe", "user.doe@gmail.com")


@pytest.fixture
def users(admin_user, regular_user) -> list[UserInfo]:
    return [
        admin_user,
        regular_user,
        UserInfo("member-1", "Member-1", "Doe", "member-1.doe@gmail.com"),
        UserInfo("member-2", "Member-2", "Doe", "member-2.doe@gmail.com"),
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
