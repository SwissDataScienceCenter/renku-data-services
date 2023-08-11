from renku_data_services.storage_api.config import Config
from renku_data_services.users.dummy import DummyAuthenticator


def test_config_dummy(monkeypatch):
    monkeypatch.setenv("DUMMY_STORES", "true")
    monkeypatch.setenv("VERSION", "9.9.9")

    config = Config.from_env()

    assert config.authenticator is not None
    assert isinstance(config.authenticator, DummyAuthenticator)
    assert config.storage_repo is not None
    assert config.version == "9.9.9"


def test_config_no_dummy(monkeypatch):
    monkeypatch.setenv("DUMMY_STORES", "false")
    monkeypatch.setenv("VERSION", "9.9.9")
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_USER", "admin")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "storage_db")
    monkeypatch.setenv("DB_PASSWORD", "123456")
    monkeypatch.setenv("GITLAB_URL", "localhost")

    config = Config.from_env()

    assert config.authenticator is not None
    assert config.storage_repo is not None
    assert config.version == "9.9.9"
