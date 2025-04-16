"""Models for DOIs."""

from dataclasses import dataclass

from pydantic import BaseModel, Field


@dataclass(frozen=True, eq=True, kw_only=True)
class DOIMetadata:
    """Model for DOI metadata."""

    name: str
    description: str
    keywords: list[str]


class InvenioRecordMetadata(BaseModel):
    """Representation of a record's metadata."""

    title: str | None = Field(default=None)
    description: str | None = Field(default=None)
    keywords: list[str] | None = Field(default=None)


class InvenioRecord(BaseModel):
    """Schema for the representation of a record from the InvenioRDM API."""

    metadata: InvenioRecordMetadata | None = Field(default=None)
