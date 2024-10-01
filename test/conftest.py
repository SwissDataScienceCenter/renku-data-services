"""Fixtures for testing."""

import logging
import os
import secrets
import socket
import subprocess
from collections.abc import Generator, Iterator
from multiprocessing import Lock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from hypothesis import settings
from pytest_postgresql.janitor import DatabaseJanitor
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services.app_config import Config as DataConfig
from renku_data_services.authz.config import AuthzConfig
from renku_data_services.db_config.config import DBConfig
from renku_data_services.secrets.config import Config as SecretsConfig

settings.register_profile("ci", deadline=400, max_examples=5)
settings.register_profile("dev", deadline=200, max_examples=5)

settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "dev"))


@pytest.fixture(scope="session")
def free_port() -> int:
    lock = Lock()
    with lock, socket.socket() as s:
        s.bind(("", 0))
        port = int(s.getsockname()[1])
        return port


@pytest.fixture
def authz_config(monkeypatch, free_port) -> Iterator[AuthzConfig]:
    port = free_port
    proc = subprocess.Popen(
        [
            "spicedb",
            "serve-testing",
            "--grpc-addr",
            f":{port}",
            "--readonly-grpc-enabled=false",
            "--skip-release-check=true",
            "--log-level=debug",
        ]
    )
    monkeypatch.setenv("AUTHZ_DB_HOST", "127.0.0.1")
    # NOTE: In our devcontainer setup 50051 and 50052 is taken by the running authzed instance
    monkeypatch.setenv("AUTHZ_DB_GRPC_PORT", f"{port}")
    monkeypatch.setenv("AUTHZ_DB_KEY", "renku")
    yield AuthzConfig.from_env()
    try:
        proc.terminate()
    except Exception as err:
        logging.error(f"Encountered error when shutting down Authzed DB for testing {err}")
        proc.kill()


@pytest.fixture
def db_config(monkeypatch, worker_id, authz_config) -> Iterator[DBConfig]:
    db_name = str(ULID()).lower() + "_" + worker_id
    user = os.getenv("DB_USER", "renku")
    host = os.getenv("DB_HOST", "127.0.0.1")
    port = os.getenv("DB_PORT", "5432")
    password = os.getenv("DB_PASSWORD", "renku")  # nosec: B105

    monkeypatch.setenv("DUMMY_STORES", "true")
    monkeypatch.setenv("DB_NAME", db_name)
    with DatabaseJanitor(
        user=user,
        host=host,
        port=port,
        dbname=db_name,
        version="16.2",
        password=password,
    ):
        yield DBConfig.from_env()
        DBConfig.dispose_connection()
        DBConfig._async_engine = None


@pytest.fixture
def secrets_key_pair(monkeypatch, tmp_path) -> None:
    """Create a public/private key pair to be used for secrets service tests."""

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_key_path = tmp_path / "key.priv"
    priv_key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    secrets_service_public_key = private_key.public_key()
    pub_key_path = tmp_path / "key.pub"
    pub_key_path.write_bytes(
        secrets_service_public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )

    monkeypatch.setenv("SECRETS_SERVICE_PUBLIC_KEY_PATH", pub_key_path.as_posix())
    monkeypatch.setenv("SECRETS_SERVICE_PRIVATE_KEY_PATH", priv_key_path.as_posix())


@pytest.fixture
def app_config(authz_config, db_config, monkeypatch, worker_id, secrets_key_pair) -> Generator[DataConfig, None, None]:
    monkeypatch.setenv("MAX_PINNED_PROJECTS", "5")
    monkeypatch.setenv("NB_SERVER_OPTIONS__DEFAULTS_PATH", "server_defaults.json")
    monkeypatch.setenv("NB_SERVER_OPTIONS__UI_CHOICES_PATH", "server_options.json")

    config = DataConfig.from_env()
    app_name = "app_" + str(ULID()).lower() + "_" + worker_id
    config.app_name = app_name
    yield config


@pytest.fixture
def secrets_storage_app_config(db_config: DBConfig, secrets_key_pair, monkeypatch, tmp_path) -> Iterator[DataConfig]:
    encryption_key_path = tmp_path / "encryption-key"
    encryption_key_path.write_bytes(secrets.token_bytes(32))

    monkeypatch.setenv("ENCRYPTION_KEY_PATH", encryption_key_path.as_posix())
    monkeypatch.setenv("DUMMY_STORES", "true")
    monkeypatch.setenv("DB_NAME", db_config.db_name)
    monkeypatch.setenv("MAX_PINNED_PROJECTS", "5")

    config = SecretsConfig.from_env()
    yield config


@pytest.fixture
def admin_user() -> base_models.APIUser:
    return base_models.APIUser(
        is_admin=True,
        id="some-random-id-123456",
        access_token="some-access-token",
        full_name="Admin Adminson",
        first_name="Admin",
        last_name="Adminson",
        email="admin@gmail.com",
    )  # nosec B106


@pytest.fixture
def loggedin_user() -> base_models.APIUser:
    return base_models.APIUser(is_admin=False, id="some-random-id-123456", access_token="some-access-token")  # nosec B106


def only(iterable, default=None, too_long=None):
    """From https://github.com/python/importlib_resources/blob/v5.13.0/importlib_resources/_itertools.py#L2."""
    it = iter(iterable)
    first_value = next(it, default)

    try:
        second_value = next(it)
    except StopIteration:
        pass
    else:
        msg = f"Expected exactly one item in iterable, but got {first_value!r}, {second_value!r}, and perhaps more."
        raise too_long or ValueError(msg)

    return first_value
