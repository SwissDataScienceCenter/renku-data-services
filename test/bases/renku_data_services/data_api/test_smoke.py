import pytest
from sanic import Sanic
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.config import Config
from renku_data_services.data_api.app import register_all_handlers


@pytest.mark.asyncio
async def test_smoke(app_config: Config):
    app = Sanic(app_config.app_name)
    app = register_all_handlers(app, app_config)
    test_client = SanicASGITestClient(app)
    _, res = await test_client.get("/api/data/version")
    assert res.status_code == 200
