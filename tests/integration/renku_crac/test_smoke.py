from sanic import Sanic
from sanic_testing.testing import SanicTestClient

from db.adapter import ResourcePoolRepository, UserRepository
from renku_crac.config import Config
from renku_crac.main import register_all_handlers


def test_smoke(pool_repo: ResourcePoolRepository, user_repo: UserRepository):
    config = Config(rp_repo=pool_repo, user_repo=user_repo)
    app = Sanic(config.app_name)
    app = register_all_handlers(app, config)
    test_client = SanicTestClient(app)
    _, res = test_client.get("/api/data/version")
    assert res.status_code == 200
