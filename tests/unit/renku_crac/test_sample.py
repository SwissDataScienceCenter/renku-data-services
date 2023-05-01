from sanic_testing.testing import SanicTestClient

from src.renku_crac.main import app


def test_sample():
    test_client = SanicTestClient(app)
    _, res = test_client.get("/api/data/version")
    assert res.status_code == 200
