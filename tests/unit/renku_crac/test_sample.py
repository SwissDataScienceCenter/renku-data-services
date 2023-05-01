from sanic_testing.testing import SanicTestClient

from src.renku_crac.main import create_app


def test_sample():
    test_client = SanicTestClient(create_app())
    _, res = test_client.get("/api/data/spec.json")
    assert res.status_code == 200
