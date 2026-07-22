"""Collector for gathering persisted logs."""

from abc import abstractmethod
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta

import httpx
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from renku_data_services.app_config import logging
from renku_data_services.persisted_logs import loki_api, models
from renku_data_services.persisted_logs.config import PersistedLogsConfig
from renku_data_services.persisted_logs.constants import (
    ONE_SECOND_IN_NANOS,
    PERSISTED_LOGS_NAMESPACE_LABEL_KEY,
    PERSISTED_LOGS_SESSIONS_LABEL_KEY,
    PERSISTED_LOGS_SESSIONS_LABEL_VALUE,
)
from renku_data_services.persisted_logs.db import AmaltheaSessionPersistedLogsRepository

logger = logging.getLogger(__name__)


class LokiLogReader:
    """Read logs from loki."""

    def __init__(self, config: PersistedLogsConfig, client: httpx.AsyncClient) -> None:
        self.config = config
        self.client = client
        self.client.base_url = httpx.URL(config.loki_read_base_url)

    async def get_amalthea_session_logs(
        self, limit: int = 1000, start: int | None = None, end: int | None = None
    ) -> AsyncIterator[models.UnsavedLogLine]:
        """Fetches Amalthea session logs from Loki.

        Parameters:
        - limit: max number of entries to return
        - start: start timestamp as a Unix nano timestamp
        - end: end timestamp as a Unix nano timestamp

        See also https://grafana.com/docs/loki/latest/reference/loki-http-api/#query-logs-within-a-range-of-time
        """
        params: dict[str, str | int] = dict()
        params["query"] = (
            "{"
            f'{PERSISTED_LOGS_SESSIONS_LABEL_KEY}="{PERSISTED_LOGS_SESSIONS_LABEL_VALUE}",'
            f'{PERSISTED_LOGS_NAMESPACE_LABEL_KEY}="{self.config.namespace}"'
            "}"
        )
        params["direction"] = "forward"
        params["limit"] = limit
        if start:
            params["start"] = str(start)
        if end:
            params["end"] = str(end)
        logger.info(params)
        res = await self.client.get("loki/api/v1/query_range", params=params)
        res.raise_for_status()
        logger.info(res)
        result = loki_api.LokiQueryRangeResponse.model_validate_json(res.content)
        log_line_ids: set[str] = set()

        for entry in result.data.result:
            stream: loki_api.AmaltheaSessionStream | None = None
            try:
                stream = loki_api.AmaltheaSessionStream.model_validate(entry.stream)
            except ValidationError as err:
                logger.warning(f"Skipping entry {entry.stream} because of validation error: {err}")
                continue

            try:
                launcher_id = ULID.from_str(stream.renku_io_launcher_id.upper())
            except ValueError as err:
                logger.warning(
                    f"Skipping entry {entry.stream} because renku_io_launcher_id='{stream.renku_io_launcher_id}' "
                    f"is not a valid ULID: {err}"
                )
                continue

            try:
                run_id = ULID.from_str(stream.renku_io_run_id.upper())
            except ValueError as err:
                logger.warning(
                    f"Skipping entry {entry.stream} because renku_io_run_id='{stream.renku_io_run_id}' "
                    f"is not a valid ULID: {err}"
                )
                continue

            # logger.info(stream)
            for nano_ts, log_line in entry.values:
                log_line_id = f"{nano_ts.root}::{stream.container}::{stream.pod}"

                if log_line_id in log_line_ids:
                    continue

                log_line_ids.add(log_line_id)
                yield models.UnsavedLogLine(
                    id=log_line_id,
                    user_id=stream.renku_io_safe_username,
                    run_id=run_id,
                    session_uid=stream.renku_io_session_uid,
                    launcher_id=launcher_id,
                    submission_id=stream.renku_io_submission_id,
                    container=stream.container,
                    timestamp=nano_ts.get_value(),
                    log_line=log_line,
                )


class PersistedLogsCollector:
    """Abstract class for gathering persisted logs."""

    @abstractmethod
    async def collect_persisted_logs(self) -> None:
        """Collect persisted logs from Amalthea sessions and image builds."""
        ...

    @staticmethod
    def from_config(
        config: PersistedLogsConfig,
        session_maker: Callable[..., AsyncSession],
        http_client: httpx.AsyncClient | None = None,
    ) -> "PersistedLogsCollector":
        """Construct a PersistedLogsCollector from a configuration object."""
        if config.enabled:
            if http_client is None:
                http_client = httpx.AsyncClient()
            reader = LokiLogReader(config=config, client=http_client)
            return DefaultPersistedLogsCollector(
                session_maker=session_maker,
                reader=reader,
                session_logs_repo=AmaltheaSessionPersistedLogsRepository(),
            )
        return NoopPersistedLogsCollector()


class NoopPersistedLogsCollector(PersistedLogsCollector):
    """No-op collector."""

    async def collect_persisted_logs(self) -> None:
        """Collect persisted logs from Amalthea sessions and image builds."""
        return None


class DefaultPersistedLogsCollector(PersistedLogsCollector):
    """Collector for gathering persisted logs."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        reader: LokiLogReader,
        session_logs_repo: AmaltheaSessionPersistedLogsRepository,
    ) -> None:
        self.session_maker = session_maker
        self.reader = reader
        self.session_logs_repo = session_logs_repo

    async def collect_persisted_logs(self) -> None:
        """Collect persisted logs from Amalthea sessions and image builds."""
        await self.collect_sessions_persisted_logs()
        return None

    async def collect_sessions_persisted_logs(self) -> None:
        """Collect persisted logs from Amalthea sessions."""

        async with self.session_maker() as session:
            async with session.begin():
                ts = await self.session_logs_repo.get_latest_log_timestamp(session=session)
                start = _one_hour_ago_in_nanos()
                if ts is not None and ts > start:
                    start = ts - ONE_SECOND_IN_NANOS

            # Loop to collect all logs, including late entries
            has_more = True
            current_start = start
            while has_more:
                logs_stream = self.reader.get_amalthea_session_logs(start=current_start)
                async with session.begin():
                    result = await self.session_logs_repo.insert_session_logs(session=session, logs_stream=logs_stream)
                    current_start = result.last_timestamp + 1
                    has_more = result.log_count > 1

            async with session.begin():
                ts = await self.session_logs_repo.get_latest_log_timestamp(session=session)
                logger.info(f"Latest session log timestamp: {ts}")

        return None


def _one_hour_ago_in_nanos() -> int:
    """Returns the Unix nano timestamp corresponding to one hour ago."""
    dt = datetime.now(tz=UTC) - timedelta(hours=1)
    return int(dt.timestamp() * 1e6) * 1000
