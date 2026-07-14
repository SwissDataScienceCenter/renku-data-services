"""Collector for gathering persisted logs."""

import httpx
from pydantic import ValidationError

from renku_data_services.app_config import logging
from renku_data_services.persisted_logs import loki_api
from renku_data_services.persisted_logs.config import PersistedLogsConfig
from renku_data_services.persisted_logs.constants import (
    PERSISTED_LOGS_NAMESPACE_LABEL_KEY,
    PERSISTED_LOGS_SESSIONS_LABEL_KEY,
    PERSISTED_LOGS_SESSIONS_LABEL_VALUE,
)

logger = logging.getLogger(__name__)


class LokiLogReader:
    """Read logs from loki."""

    def __init__(self, config: PersistedLogsConfig, client: httpx.AsyncClient) -> None:
        self.config = config
        self.client = client
        self.client.base_url = httpx.URL(config.loki_read_base_url)

    async def get_amalthea_session_logs(self) -> None:
        """Returns log streams from Amalthea sessions."""
        params: dict[str, str] = dict()
        params["query"] = (
            "{"
            f'{PERSISTED_LOGS_SESSIONS_LABEL_KEY}="{PERSISTED_LOGS_SESSIONS_LABEL_VALUE}",'
            f'{PERSISTED_LOGS_NAMESPACE_LABEL_KEY}="{self.config.namespace}"'
            "}"
        )
        params["direction"] = "forward"
        logger.info(params)
        res = await self.client.get("loki/api/v1/query_range", params=params)
        res.raise_for_status()
        logger.info(res)
        result = loki_api.LokiQueryRangeResponse.model_validate_json(res.content)
        # logger.info(result)

        log_line_ids: set[str] = set()

        for entry in result.data.result:
            # logger.info(entry)
            stream: loki_api.AmaltheaSessionStream | None = None
            try:
                stream = loki_api.AmaltheaSessionStream.model_validate(entry.stream)
            except ValidationError as err:
                logger.warning(f"Skipping entry {entry.stream} because of validation error: {err}")
                continue

            logger.info(stream)
            for nano_ts, log_line in entry.values:
                logger.info(nano_ts.get_value())
                logger.info(log_line)

                log_line_id = f"{nano_ts.root}::{stream.container}::{stream.pod}"

                if log_line_id in log_line_ids:
                    logger.info(f"Already saw: {log_line_id}")

                log_line_ids.add(log_line_id)

        pass


class PersistedLogsCollector:
    """Collector for gathering persisted logs."""

    pass
