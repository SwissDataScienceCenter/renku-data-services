from sanic import Sanic
from sanic_testing.testing import SanicTestClient

from db.adapter import ResourcePoolRepository, UserRepository
from k8s.clients import DummyCoreClient, DummySchedulingClient
from k8s.quota import QuotaRepository
from renku_crc.config import Config
from renku_crc.main import register_all_handlers
from users.dummy import DummyAuthenticator, DummyUserStore


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
