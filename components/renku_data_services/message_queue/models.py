"""Basic models used for communication with the message queue."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from ulid import ULID


@dataclass
class Reprovisioning:
    """A reprovisioning."""

    id: ULID
    start_date: datetime = field(default_factory=lambda: datetime.now(UTC).replace(microsecond=0))
