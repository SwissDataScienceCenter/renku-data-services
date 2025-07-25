import secrets
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

import renku_data_services.data_api.config as conf
from renku_data_services.authn.dummy import DummyAuthenticator
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.db_config.config import DBConfig
from renku_data_services.k8s.clients import DummyCoreClient, DummySchedulingClient
from renku_data_services.users.dummy_kc_api import DummyKeycloakAPI


@pytest_asyncio.fixture
async def dependencies_dummy_fixture(monkeypatch):
    monkeypatch.setenv("DUMMY_STORES", "true")
    monkeypatch.setenv("VERSION", "9.9.9")
    yield DependencyManager.from_env()
    # NOTE: _async_engine is a class variable and it persist across tests because pytest loads
    # all things once at the beginning of hte tests. So we reset it here so that it does not affect
    # subsequent tests.
    await DBConfig.dispose_connection()


def test_config_dummy(dependencies_dummy_fixture: DependencyManager) -> None:
    dm = dependencies_dummy_fixture
    assert dm.authenticator is not None
    assert isinstance(dm.authenticator, DummyAuthenticator)
    assert dm.storage_repo is not None
    assert dm.rp_repo is not None
    assert dm.user_repo is not None
    assert dm.project_repo is not None
    assert dm.session_repo is not None
    assert dm.user_preferences_repo is not None
    assert dm.config.version == "9.9.9"


@pytest_asyncio.fixture
async def config_no_dummy_fixture(monkeypatch, secrets_key_pair, tmp_path):
    encryption_key_path = tmp_path / "encryption-key"
    encryption_key_path.write_bytes(secrets.token_bytes(32))

    monkeypatch.setenv("ENCRYPTION_KEY_PATH", encryption_key_path.as_posix())
    monkeypatch.setenv("DUMMY_STORES", "false")
    monkeypatch.setenv("VERSION", "9.9.9")
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_USER", "admin")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "storage_db")
    monkeypatch.setenv("DB_PASSWORD", "123456")
    monkeypatch.setenv("REDIS_HOST", "localhost")
    monkeypatch.setenv("REDIS_PORT", "5312")
    monkeypatch.setenv("REDIS_DATABASE", "3")
    monkeypatch.setenv("REDIS_MASTER_SET", "my_master")
    monkeypatch.setenv("REDIS_IS_SENTINEL", "false")
    monkeypatch.setenv("REDIS_PASSWORD", "mypw")
    monkeypatch.setenv("GITLAB_URL", "https://localhost")
    monkeypatch.setenv("KEYCLOAK_URL", "localhost")
    monkeypatch.setenv("KEYCLOAK_TOKEN_SIGNATURE_ALGS", "test")
    monkeypatch.setenv("KEYCLOAK_CLIENT_ID", "data-service")
    monkeypatch.setenv("KEYCLOAK_CLIENT_SECRET", "data-service-client-secret")
    monkeypatch.setattr(conf, "oidc_discovery", lambda _, __: {"jwks_uri": "localhost"})
    monkeypatch.setattr(conf, "PyJWKClient", lambda _: MagicMock())
    monkeypatch.setattr(conf, "K8sCoreClient", lambda: DummyCoreClient({}, {}))
    monkeypatch.setattr(conf, "K8sSchedulingClient", lambda: DummySchedulingClient({}))

    def patch_kc_api(*args, **kwargs):
        return DummyKeycloakAPI()

    monkeypatch.setattr(conf, "KeycloakAPI", patch_kc_api)

    yield DependencyManager.from_env()
    # NOTE: _async_engine is a class variable and it persist across tests because pytest loads
    # all things once at the beginning of hte tests. So we reset it here so that it does not affect
    # subsequent tests.
    await DBConfig.dispose_connection()


@pytest.mark.skip(reason="Re-enable when the k8s cluster for CI is fully setup")  # TODO: address in followup PR
def test_config_no_dummy(config_no_dummy_fixture: DependencyManager) -> None:
    config = config_no_dummy_fixture
    assert config.authenticator is not None
    assert config.storage_repo is not None
    assert config.rp_repo is not None
    assert config.user_repo is not None
    assert config.project_repo is not None
    assert config.session_repo is not None
    assert config.user_preferences_repo is not None
    assert config.version == "9.9.9"
