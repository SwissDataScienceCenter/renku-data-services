"""Base models for secrets."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel


@dataclass(eq=True, frozen=True)
class Secret(BaseModel):
    """Secret objects."""

    name: str
    encrypted_value: bytes = field(repr=False)
    id: str | None = field(default=None)
    modification_date: datetime = field(default_factory=lambda: datetime.now(UTC).replace(microsecond=0))
