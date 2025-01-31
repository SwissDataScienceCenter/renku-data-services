import logging
import socket
import subprocess
from asyncio import sleep
from multiprocessing import Lock
from os import getenv

import httpx
import pytest
import pytest_asyncio
from ulid import ULID

from renku_data_services.solr import entity_schema
from renku_data_services.solr.solr_client import SolrClientConfig
from renku_data_services.solr.solr_migrate import SchemaMigrator


@pytest.fixture(scope="session")
def free_port() -> int:
    lock = Lock()
    with lock, socket.socket() as s:
        s.bind(("", 0))
        port = int(s.getsockname()[1])
        return port


@pytest.fixture(scope="session")
def monkeysession():
    mpatch = pytest.MonkeyPatch()
    yield mpatch
    mpatch.undo()


@pytest.fixture(scope="session")
def solr_bin_path():
    solr_bin = getenv("SOLR_BIN_PATH")
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
                    raise Exception(f"Cannot connect to solr, gave up after {tries} tries.")
                else:
                    tries = tries + 1
                    await sleep(1)


@pytest_asyncio.fixture(scope="session")
async def solr_instance(tmp_path_factory, free_port, monkeysession, solr_bin_path):
    solr_root = tmp_path_factory.mktemp("solr")
    solr_bin = solr_bin_path
    port = free_port
    logging.info(f"Starting SOLR at port {port}")
    proc = subprocess.Popen(
        [
            solr_bin,
            "start",
            "-f",
            "--host",
            "localhost",
            "--port",
            f"{port}",
            "-s",
            f"{solr_root}",
            "-t",
            f"{solr_root}",
        ],
        env={"PATH": getenv("PATH", ""), "SOLR_LOGS_DIR": f"{solr_root}", "SOLR_ULIMIT_CHECKS": "false"},
    )
    monkeysession.setenv("SOLR_HOST", "localhost")
    monkeysession.setenv("SOLR_PORT", f"{port}")
    monkeysession.setenv("SOLR_ROOT_DIR", solr_root)

    await __wait_for_solr("localhost", port)

    yield
    try:
        proc.terminate()
    except Exception as err:
        logging.error(f"Encountered error when shutting down solr for testing {err}")
        proc.kill()


@pytest.fixture
def solr_core(solr_instance, monkeysession):
    core_name = str(ULID()).lower()
    monkeysession.setenv("SOLR_CORE_NAME", core_name)
    return core_name


@pytest.fixture()
def solr_config(solr_core, solr_bin_path):
    core = solr_core
    solr_host = getenv("SOLR_HOST")
    solr_port = getenv("SOLR_PORT")
    solr_config = SolrClientConfig(base_url=f"http://{solr_host}:{solr_port}", core=core)
    solr_bin = solr_bin_path
    subprocess.run([solr_bin, "create", "-c", core])

    # TODO this is annoying!
    dir = getenv("SOLR_ROOT_DIR")
    conf_file = f"{dir}/{core}/conf/managed-schema.xml"
    subprocess.run(["chmod", "644", conf_file])

    return solr_config


@pytest_asyncio.fixture()
async def solr_search(solr_config):
    migrator = SchemaMigrator(solr_config)
    migrations = entity_schema.all_migrations.copy()
    result = await migrator.migrate(migrations)
    assert result.migrationsRun == len(migrations)
    return solr_config
