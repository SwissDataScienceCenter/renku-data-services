"""Pydantic models for the Loki API."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, RootModel


class Base(BaseModel):
    """Base CRD specification."""

    model_config = ConfigDict(
        # Do not exclude unknown properties.
        extra="allow"
    )


class LokiQueryRangeResponse(Base):
    """Response from the query range endpoint (streams only)."""

    status: LokiQueryRangeResponseStatus
    data: LokiQueryRangeResponseData


class LokiQueryRangeResponseStatus(StrEnum):
    """Response status."""

    success = "success"


class LokiQueryRangeResponseData(Base):
    """Response data from the query range endpoint (streams only)."""

    result_type: LokiQueryRangeResponseResultType = Field(..., alias="resultType")
    result: list[LokiQueryRangeResponseStream]


class LokiQueryRangeResponseResultType(StrEnum):
    """Result type."""

    streams = "streams"


class LokiQueryRangeResponseStream(Base):
    """Loki log stream."""

    stream: dict[str, str]
    values: list[tuple[NanoTimestamp, str]]


class NanoTimestamp(RootModel[str]):
    """Unix timestamp in nanoseconds."""

    root: str = Field(..., pattern="\\d+")

    def get_value(self) -> int:
        """Return the timestamp as a big integer."""
        return int(self.root)


class AmaltheaSessionStream(Base):
    """Loki stream labels for logs extracted from an Amalthea session."""

    container: str
    pod: str
    renku_io_launcher_id: str
    renku_io_project_id: str | None = None
    renku_io_run_id: str
    renku_io_safe_username: str
    renku_io_session_type: str | None = None
    renku_io_session_uid: str | None = None
    renku_io_submission_id: str | None = None
