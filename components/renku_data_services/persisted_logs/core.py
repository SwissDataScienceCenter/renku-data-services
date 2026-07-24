"""Business logic for persisted logs."""

from datetime import UTC, datetime
from typing import Self

from renku_data_services.persisted_logs.constants import ONE_SECOND_IN_NANOS


class NanoTimestamp(int):
    """Unix timestamp in nanoseconds."""

    def to_datetime(self) -> datetime:
        """Return the corresponding datetime, trucated to xxx precision."""
        return datetime.fromtimestamp(self / float(ONE_SECOND_IN_NANOS), tz=UTC)

    @classmethod
    def from_datetime(cls, dt: datetime) -> Self:
        """Create a nano timestamp from a datetime object."""
        return cls(int(dt.timestamp() * 1e6) * 1000)
