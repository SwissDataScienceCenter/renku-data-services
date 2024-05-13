"""Fixtures for testing."""

import os
import secrets
from collections.abc import Iterator

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from hypothesis import settings
from pytest_postgresql import factories

import renku_data_services.base_models as base_models
from renku_data_services.app_config import Config as DataConfig
from renku_data_services.migrations.core import run_migrations_for_app as run_data_service_migrations_for_app
from renku_data_services.secrets.config import Config as SecretsConfig

settings.register_profile("ci", deadline=400, max_examples=5)
settings.register_profile("dev", deadline=200, max_examples=5)

settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "dev"))


def get_init_db(component):
    def init_db(**kwargs):
        """Run database migrations so they don't need to run on every test."""
        dummy_stores = os.environ.get("DUMMY_STORES")
        name = os.environ.get("DB_NAME")
        user = os.environ.get("DB_USER")
        pw = os.environ.get("DB_PASSWORD")
        host = os.environ.get("DB_HOST")
        port = os.environ.get("DB_PORT")

        os.environ["DUMMY_STORES"] = "true"
        os.environ["DB_NAME"] = kwargs["dbname"]
        os.environ["DB_USER"] = kwargs["user"]
        os.environ["DB_PASSWORD"] = kwargs["password"]
        os.environ["DB_HOST"] = kwargs["host"]
        os.environ["DB_PORT"] = str(kwargs["port"])

        if component == "renku-data-service" or component == "secrets-storage":
            run_data_service_migrations_for_app("common")
        else:
            raise ValueError("Invalid component name")

        if dummy_stores:
            os.environ["DUMMY_STORES"] = dummy_stores
        else:
            del os.environ["DUMMY_STORES"]
        if name:
            os.environ["DB_NAME"] = name
        else:
            del os.environ["DB_NAME"]
        if user:
            os.environ["DB_USER"] = user
        else:
            del os.environ["DB_USER"]
        if pw:
            os.environ["DB_PASSWORD"] = pw
        else:
            del os.environ["DB_PASSWORD"]
        if host:
            os.environ["DB_HOST"] = host
        else:
            del os.environ["DB_HOST"]
        if port:
            os.environ["DB_PORT"] = port
        else:
            del os.environ["DB_PORT"]

    return init_db


postgresql_in_docker = factories.postgresql_noproc(load=[get_init_db("renku-data-service")])
postgresql = factories.postgresql("postgresql_in_docker")


@pytest.fixture
def secrets_key_pair(monkeypatch, tmp_path):
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
def app_config(postgresql, secrets_key_pair, monkeypatch) -> Iterator[DataConfig]:
    monkeypatch.setenv("DUMMY_STORES", "true")
    monkeypatch.setenv("DB_NAME", postgresql.info.dbname)
    monkeypatch.setenv("MAX_PINNED_PROJECTS", "5")

    config = DataConfig.from_env()
    yield config
    monkeypatch.delenv("DUMMY_STORES", raising=False)
    # NOTE: This is necessary because the postgresql pytest extension does not close
    # the async connection/pool we use in the config and the connection will succeed in the first
    # test but fail in all others if the connection is not disposed at the end of every test.
    config.db.dispose_connection()


@pytest.fixture
def secrets_storage_app_config(postgresql, secrets_key_pair, monkeypatch, tmp_path) -> Iterator[DataConfig]:
    encryption_key_path = tmp_path / "encryption-key"
    encryption_key_path.write_bytes(secrets.token_bytes(32))

    monkeypatch.setenv("ENCRYPTION_KEY_PATH", encryption_key_path.as_posix())
    monkeypatch.setenv("DUMMY_STORES", "true")
    monkeypatch.setenv("DB_NAME", postgresql.info.dbname)
    monkeypatch.setenv("MAX_PINNED_PROJECTS", "5")

    config = SecretsConfig.from_env()
    yield config
    monkeypatch.delenv("DUMMY_STORES", raising=False)
    # NOTE: This is necessary because the postgresql pytest extension does not close
    # the async connection/pool we use in the config and the connection will succeed in the first
    # test but fail in all others if the connection is not disposed at the end of every test.
    config.db.dispose_connection()


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
