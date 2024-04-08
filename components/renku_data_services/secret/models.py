"""Models for secrets."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Optional

from pydantic import BaseModel

from renku_data_services import errors


@dataclass(frozen=True, eq=True, kw_only=True)
class Secret(BaseModel):
    """Secret model."""

    id: Optional[str]
    name: str
    value: str = field(repr=False)
    modification_date: Optional[datetime] = None

    @classmethod
    def from_dict(cls, data: dict) -> "Secret":
        """Create the model from a plain dictionary."""
        if "name" not in data:
            raise errors.ValidationError(message="'name' not set")
        if "value" not in data:
            raise errors.ValidationError(message="'value' not set")

        id = data.get("id")
        name = data["name"]
        value = data["value"]
        modification_date = data.get("modification_date") or datetime.now(UTC).replace(microsecond=0)

        return cls(id=id, name=name, modification_date=modification_date, value=value)
