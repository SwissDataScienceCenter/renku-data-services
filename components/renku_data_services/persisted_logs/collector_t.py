"""Temp: for testing with local port-forwarding..."""

import asyncio

import httpx

from renku_data_services.app_config import logging
from renku_data_services.persisted_logs.collector import LokiLogReader
from renku_data_services.persisted_logs.config import PersistedLogsConfig

logger = logging.getLogger(__name__)


def _main() -> None:
    logging.configure_logging()
    config = PersistedLogsConfig(
        enabled=True,
        # loki_read_base_url="http://host.docker.internal:3100/",
        loki_read_base_url="http://10.6.0.96:3100/",
        namespace="renku",
    )
    reader = LokiLogReader(config, client=httpx.AsyncClient())

    async def get_some_logs() -> None:
        async for log_line in reader.get_amalthea_session_logs():
            logger.info(log_line)

    asyncio.run(get_some_logs())


if __name__ == "__main__":
    _main()
