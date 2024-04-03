from test.bases.renku_data_services.keycloak_sync.test_sync import get_kc_users

import pytest_asyncio
from sanic import Sanic
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.app_config.config import Config
from renku_data_services.data_api.app import register_all_handlers
from renku_data_services.users.dummy_kc_api import DummyKeycloakAPI
from renku_data_services.users.models import UserInfo


@pytest_asyncio.fixture
async def sanic_client(app_config: Config, users: list[UserInfo]) -> SanicASGITestClient:
    app_config.kc_api = DummyKeycloakAPI(users=get_kc_users(users))
    app = Sanic(app_config.app_name)
    app = register_all_handlers(app, app_config)
    await app_config.kc_user_repo.initialize(app_config.kc_api)
    await app_config.group_repo.generate_user_namespaces()
    return SanicASGITestClient(app)
