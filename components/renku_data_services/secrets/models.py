"""Base models for secrets."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class Secret(BaseModel):
    """Secret objects."""

    name: str
    encrypted_value: bytes = Field(repr=False)
    id: str | None = Field(default=None, init=False)
    modification_date: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(microsecond=0), init=False)
