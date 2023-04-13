from sanic_testing.testing import SanicTestClient

from src.renku_crack.app import app


def test_sample():
    test_client = SanicTestClient(app)
    _, res = test_client.get("/")
    assert res.status_code == 200
