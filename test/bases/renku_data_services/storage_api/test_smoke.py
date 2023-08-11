from sanic import Sanic
from sanic_testing.testing import SanicTestClient

from renku_data_services.storage_adapters import StorageRepository
from renku_data_services.storage_api.app import register_all_handlers
from renku_data_services.storage_api.config import Config
from renku_data_services.users.dummy import DummyAuthenticator


def test_smoke(storage_repo: StorageRepository):
    config = Config(
        storage_repo=storage_repo,
        authenticator=DummyAuthenticator(admin=True),
    )
    app = Sanic(config.app_name)
    app = register_all_handlers(app, config)
    test_client = SanicTestClient(app)
    _, res = test_client.get("/api/storage/version")
    assert res.status_code == 200
