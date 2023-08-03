from renku_data_services.resource_pool_adapters import ResourcePoolRepository, UserRepository
from renku_data_services.k8s.clients import DummyCoreClient, DummySchedulingClient
from renku_data_services.k8s.quota import QuotaRepository
from renku_data_services.users.dummy import DummyAuthenticator, DummyUserStore
from sanic import Sanic
from sanic_testing.testing import SanicTestClient

from renku_data_services.crc_api.app import register_all_handlers
from renku_data_services.crc_api.config import Config


def test_smoke(pool_repo: ResourcePoolRepository, user_repo: UserRepository):
    config = Config(
        rp_repo=pool_repo,
        user_repo=user_repo,
        user_store=DummyUserStore(),
        authenticator=DummyAuthenticator(admin=True),
        quota_repo=QuotaRepository(DummyCoreClient({}), DummySchedulingClient({})),
    )
    app = Sanic(config.app_name)
    app = register_all_handlers(app, config)
    test_client = SanicTestClient(app)
    _, res = test_client.get("/api/data/version")
    assert res.status_code == 200
