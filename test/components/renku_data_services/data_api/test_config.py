from unittest.mock import MagicMock

import renku_data_services.config.config as conf
from renku_data_services.authn.dummy import DummyAuthenticator
from renku_data_services.k8s.clients import DummyCoreClient, DummySchedulingClient


def test_config_dummy(monkeypatch):
    monkeypatch.setenv("DUMMY_STORES", "true")
    monkeypatch.setenv("VERSION", "9.9.9")

    config = conf.Config.from_env()

    assert config.authenticator is not None
    assert isinstance(config.authenticator, DummyAuthenticator)
    assert config.storage_repo is not None
    assert config.rp_repo is not None
    assert config.user_repo is not None
    assert config.project_repo is not None
    assert config.version == "9.9.9"


def test_config_no_dummy(monkeypatch):
    monkeypatch.setenv("DUMMY_STORES", "false")
    monkeypatch.setenv("VERSION", "9.9.9")
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_USER", "admin")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "storage_db")
    monkeypatch.setenv("DB_PASSWORD", "123456")
    monkeypatch.setenv("GITLAB_URL", "https://localhost")
    monkeypatch.setenv("KEYCLOAK_URL", "localhost")
    monkeypatch.setenv("KEYCLOAK_TOKEN_SIGNATURE_ALGS", "test")
    monkeypatch.setattr(conf, "_oidc_discovery", lambda _, __: {"jwks_uri": "localhost"})
    monkeypatch.setattr(conf, "PyJWKClient", lambda _: MagicMock())
    monkeypatch.setattr(conf, "K8sCoreClient", lambda: DummyCoreClient({}))
    monkeypatch.setattr(conf, "K8sSchedulingClient", lambda: DummySchedulingClient({}))

    config = conf.Config.from_env()

    assert config.authenticator is not None
    assert config.storage_repo is not None
    assert config.rp_repo is not None
    assert config.user_repo is not None
    assert config.project_repo is not None
    assert config.version == "9.9.9"
