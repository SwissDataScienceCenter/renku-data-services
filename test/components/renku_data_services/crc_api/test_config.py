from renku_data_services.crc_api.config import Config
from renku_data_services.users.dummy import DummyAuthenticator


def test_config_dummy(monkeypatch):
    monkeypatch.setenv("DUMMY_STORES", "true")
    monkeypatch.setenv("VERSION", "9.9.9")

    config = Config.from_env()

    assert config.authenticator is not None
    assert isinstance(config.authenticator, DummyAuthenticator)
    assert config.rp_repo is not None
    assert config.user_repo is not None
    assert config.version == "9.9.9"
