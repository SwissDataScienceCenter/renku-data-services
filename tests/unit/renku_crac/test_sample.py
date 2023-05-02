from sanic_testing.testing import SanicTestClient

from renku_crac.main import create_app


def test_sample():
    app = create_app()
    test_client = SanicTestClient(app)
    _, res = test_client.get("/api/data/version")
    assert res.status_code == 200
