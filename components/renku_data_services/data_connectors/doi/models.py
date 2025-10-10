"""Models for DOIs."""

from dataclasses import dataclass
from typing import Any

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


class DataverseMetadataBlockCitationField(BaseModel):
    """A metadata field of citation metadata."""

    type_name: str = Field(alias="typeName")
    multiple: bool = Field()
    type_class: str = Field(alias="typeClass")
    value: Any = Field()  # TODO: can we find better types here?


class DataverseMetadataBlockCitation(BaseModel):
    """Representation of citation metadata."""

    fields: list[DataverseMetadataBlockCitationField] = Field(default_factory=list)


class DataverseMetadataBlocks(BaseModel):
    """Represents metadata of a Dataverse dataset."""

    citation: DataverseMetadataBlockCitation | None = Field()


class DataverseDatasetVersion(BaseModel):
    """Representation of a dataset version."""

    metadata_blocks: DataverseMetadataBlocks | None = Field(alias="metadataBlocks")


class DataverseDataset(BaseModel):
    """Representation of a dataset in Dataverse."""

    latest_version: DataverseDatasetVersion | None = Field(alias="latestVersion")


class DataverseDatasetResponse(BaseModel):
    """DataverseDatasetResponse is returned by the Dataverse dataset API."""

    status: str = Field()
    data: DataverseDataset | None = Field()
