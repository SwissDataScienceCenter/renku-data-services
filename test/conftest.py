"""Fixtures for testing."""

import asyncio
import logging as ll
import os
import secrets
import socket
import stat
import subprocess
from collections.abc import AsyncGenerator
from distutils.dir_util import copy_tree
from multiprocessing import Lock
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
import uvloop
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from hypothesis import settings
from pytest_postgresql.janitor import DatabaseJanitor
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services.app_config import logging
from renku_data_services.authz.config import AuthzConfig
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.db_config.config import DBConfig
from renku_data_services.secrets_storage_api.dependencies import DependencyManager as SecretsDependencyManager
from renku_data_services.solr import entity_schema
from renku_data_services.solr.solr_client import SolrClientConfig
from renku_data_services.solr.solr_migrate import SchemaMigrator
from renku_data_services.users import models as user_preferences_models
from test.utils import TestDependencyManager


def __make_logging_config() -> logging.Config:
    def_cfg = logging.Config(
        root_level=ll.ERROR,
        app_level=ll.ERROR,
        format_style=logging.LogFormatStyle.plain,
        override_levels={ll.ERROR: set(["alembic", "sanic"])},
    )
    env_cfg = logging.Config.from_env()
    def_cfg.update_override_levels(env_cfg.override_levels)

    test_cfg = logging.Config.from_env(prefix="TEST_")
    def_cfg.update_override_levels(test_cfg.override_levels)
    return def_cfg


logging.configure_logging(__make_logging_config())


logger = logging.getLogger(__name__)

settings.register_profile("ci", deadline=400, max_examples=5)
settings.register_profile("dev", deadline=200, max_examples=5)

settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "dev"))

# there are some cases where sanic inadvertently sets the loop policy to uvloop
# This can cause issues if the main loop isn't an uvloop loop, so we force the use of uvloop
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


@pytest.fixture(scope="session")
def event_loop():
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        policy = asyncio.get_event_loop_policy()
        loop = policy.new_event_loop()
    yield loop
    print("closing event loop")
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def monkeysession():
    mpatch = pytest.MonkeyPatch()
    yield mpatch
    mpatch.undo()


def free_port() -> int:
    lock = Lock()
    with lock, socket.socket() as s:
        s.bind(("", 0))
        port = int(s.getsockname()[1])
        return port


@pytest_asyncio.fixture(scope="session")
async def authz_setup(monkeysession) -> AsyncGenerator[None, None]:
    port = free_port()
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
    monkeysession.setenv("AUTHZ_DB_HOST", "127.0.0.1")
    # NOTE: In our devcontainer setup 50051 and 50052 is taken by the running authzed instance
    monkeysession.setenv("AUTHZ_DB_GRPC_PORT", f"{port}")
    monkeysession.setenv("AUTHZ_DB_KEY", "renku")
    yield
    try:
        proc.terminate()
    except Exception as err:
        logger.error(f"Encountered error when shutting down Authzed DB for testing {err}")
        proc.kill()


@pytest_asyncio.fixture
async def db_config(monkeypatch, worker_id, authz_setup) -> AsyncGenerator[DBConfig, None]:
    db_name = "R_" + str(ULID()).lower() + "_" + worker_id
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
        template_dbname="renku_template",
    ):
        yield DBConfig.from_env()
        await DBConfig.dispose_connection()


@pytest_asyncio.fixture
async def db_instance(monkeysession, worker_id, app_manager, event_loop) -> AsyncGenerator[DBConfig, None]:
    db_name = "R_" + str(ULID()).lower() + "_" + worker_id
    user = os.getenv("DB_USER", "renku")
    host = os.getenv("DB_HOST", "127.0.0.1")
    port = os.getenv("DB_PORT", "5432")
    password = os.getenv("DB_PASSWORD", "renku")  # nosec: B105

    monkeysession.setenv("DUMMY_STORES", "true")
    monkeysession.setenv("DB_NAME", db_name)
    with DatabaseJanitor(
        user=user,
        host=host,
        port=port,
        dbname=db_name,
        version="16.2",
        password=password,
        template_dbname="renku_template",
    ):
        db = DBConfig.from_env()
        app_manager.config.db.push(db)
        yield db
        await app_manager.config.db.pop()


@pytest_asyncio.fixture
async def authz_instance(app_manager: DependencyManager, monkeypatch) -> AsyncGenerator[AuthzConfig]:
    monkeypatch.setenv("AUTHZ_DB_KEY", f"renku-{uuid4().hex}")
    app_manager.config.authz_config.push(AuthzConfig.from_env())
    yield app_manager.config.authz_config
    app_manager.config.authz_config.pop()


@pytest_asyncio.fixture(scope="session")
async def secrets_key_pair(monkeysession, tmpdir_factory) -> None:
    """Create a public/private key pair to be used for secrets service tests."""
    tmp_path = tmpdir_factory.mktemp("secrets_key")

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_key_path = Path(tmp_path) / "key.priv"
    priv_key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    secrets_service_public_key = private_key.public_key()
    pub_key_path = Path(tmp_path) / "key.pub"
    pub_key_path.write_bytes(
        secrets_service_public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )

    monkeysession.setenv("SECRETS_SERVICE_PUBLIC_KEY_PATH", pub_key_path.as_posix())
    monkeysession.setenv("SECRETS_SERVICE_PRIVATE_KEY_PATH", priv_key_path.as_posix())


@pytest_asyncio.fixture(scope="session")
async def dummy_users():
    return [
        user_preferences_models.UnsavedUserInfo(id="user1", first_name="user1", last_name="doe", email="user1@doe.com"),
        user_preferences_models.UnsavedUserInfo(id="user2", first_name="user2", last_name="doe", email="user2@doe.com"),
    ]


@pytest_asyncio.fixture(scope="session")
async def app_manager(
    authz_setup, monkeysession, worker_id, secrets_key_pair, dummy_users
) -> AsyncGenerator[DependencyManager, None]:
    monkeysession.setenv("DUMMY_STORES", "true")
    monkeysession.setenv("MAX_PINNED_PROJECTS", "5")
    monkeysession.setenv("NB_SERVER_OPTIONS__DEFAULTS_PATH", "server_defaults.json")
    monkeysession.setenv("NB_SERVER_OPTIONS__UI_CHOICES_PATH", "server_options.json")

    dm = TestDependencyManager.from_env(dummy_users)

    app_name = "app_" + str(ULID()).lower() + "_" + worker_id
    dm.app_name = app_name
    yield dm


@pytest_asyncio.fixture
async def app_manager_instance(app_manager, db_instance, authz_instance) -> AsyncGenerator[DependencyManager, None]:
    app_manager.metrics.reset_mock()
    yield app_manager


@pytest_asyncio.fixture
async def secrets_storage_app_manager(
    db_config: DBConfig, secrets_key_pair, monkeypatch, tmp_path
) -> AsyncGenerator[SecretsDependencyManager, None]:
    encryption_key_path = tmp_path / "encryption-key"
    encryption_key_path.write_bytes(secrets.token_bytes(32))

    monkeypatch.setenv("ENCRYPTION_KEY_PATH", encryption_key_path.as_posix())
    monkeypatch.setenv("DUMMY_STORES", "true")
    monkeypatch.setenv("DB_NAME", db_config.db_name)
    monkeypatch.setenv("MAX_PINNED_PROJECTS", "5")

    dm = SecretsDependencyManager.from_env()
    yield dm


@pytest_asyncio.fixture
async def admin_user() -> base_models.APIUser:
    return base_models.APIUser(
        is_admin=True,
        id="some-random-id-123456",
        access_token="some-access-token",
        full_name="Admin Adminson",
        first_name="Admin",
        last_name="Adminson",
        email="admin@gmail.com",
    )  # nosec B106


@pytest_asyncio.fixture
async def loggedin_user() -> base_models.APIUser:
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


@pytest.fixture(scope="session")
def solr_bin_path():
    solr_bin = os.getenv("SOLR_BIN_PATH")
    if solr_bin is None:
        solr_bin = "solr"
    return solr_bin


async def __wait_for_solr(host: str, port: int) -> None:
    tries = 0
    with httpx.Client() as c:
        while True:
            try:
                c.get(f"http://{host}:{port}/solr")
                return None
            except Exception as err:
                print(err)
                if tries >= 20:
                    raise Exception(f"Cannot connect to solr, gave up after {tries} tries.") from err
                else:
                    tries = tries + 1
                    await asyncio.sleep(1)


@pytest_asyncio.fixture(scope="session")
async def solr_instance(tmp_path_factory, monkeysession, solr_bin_path):
    solr_root = tmp_path_factory.mktemp("solr")
    solr_bin = solr_bin_path
    port = free_port()
    logger.info(f"Starting SOLR at port {port}")
    args = [
        solr_bin,
        "start",
        "-f",
        "--jvm-opts",
        "-Xmx256M -Xms256M",
        "--host",
        "localhost",
        "--port",
        f"{port}",
        "-s",
        f"{solr_root}",
        "-t",
        f"{solr_root}",
        "--user-managed",
    ]
    logger.info(f"Starting SOLR via: {args}")
    proc = subprocess.Popen(
        args,
        env={"PATH": os.getenv("PATH", ""), "SOLR_LOGS_DIR": f"{solr_root}", "SOLR_ULIMIT_CHECKS": "false"},
    )
    monkeysession.setenv("SOLR_TEST_PORT", f"{port}")
    monkeysession.setenv("SOLR_ROOT_DIR", solr_root)
    monkeysession.setenv("SOLR_URL", f"http://localhost:{port}")

    await __wait_for_solr("localhost", port)

    yield
    try:
        proc.terminate()
    except Exception as err:
        logger.error(f"Encountered error when shutting down solr for testing {err}")
        proc.kill()


@pytest.fixture
def solr_core(solr_instance, monkeypatch):
    core_name = "test_core_" + str(ULID()).lower()[-12:]
    monkeypatch.setenv("SOLR_TEST_CORE", core_name)
    monkeypatch.setenv("SOLR_CORE", core_name)
    return core_name


@pytest.fixture()
def solr_config(solr_core, solr_bin_path):
    core = solr_core
    solr_port = os.getenv("SOLR_TEST_PORT")
    if solr_port is None:
        raise ValueError("No SOLR_TEST_PORT env variable found")

    solr_url = f"http://localhost:{solr_port}"
    solr_config = SolrClientConfig(base_url=solr_url, core=core)
    solr_bin = solr_bin_path
    result = subprocess.run([solr_bin, "create", "--solr-url", solr_url, "-c", core])
    result.check_returncode()

    # Unfortunately, solr creates core directories with only read permissions
    # Then changing the schema via the api fails, because it can't write to that file
    root_dir = os.getenv("SOLR_ROOT_DIR")
    conf_file = f"{root_dir}/{core}/conf/managed-schema.xml"
    os.chmod(conf_file, stat.S_IRUSR | stat.S_IWUSR | stat.S_IROTH | stat.S_IRGRP)

    # we also need to create the configset/_default directory to make
    # core-admin commands work
    if not os.path.isdir(f"{root_dir}/configsets/_default"):
        os.makedirs(f"{root_dir}/configsets/_default")
        copy_tree(f"{root_dir}/{core}/conf", f"{root_dir}/configsets/_default/conf")

    return solr_config


@pytest_asyncio.fixture()
async def solr_search(solr_config, app_manager):
    migrator = SchemaMigrator(solr_config)
    result = await migrator.migrate(entity_schema.all_migrations)
    assert result.migrations_run == len(entity_schema.all_migrations)

    return solr_config
