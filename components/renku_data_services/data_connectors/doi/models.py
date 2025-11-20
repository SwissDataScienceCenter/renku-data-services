"""Models for DOIs."""

import re
from dataclasses import dataclass
from typing import Any, Self
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field

from renku_data_services.errors import errors


class DOI(str):
    """A doi for a dataset or a similar resource."""

    __regex = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)

    def __new__(cls, doi: str) -> Self:
        """Create a new doi.

        A few cases possible:
        doi:10.16904/12
        10.16904/12
        https://www.doi.org/10.16904/12
        http://www.doi.org/10.16904/12
        http://doi.org/10.16904/12
        """
        doi_parsed = urlparse(doi)
        doi_clean = doi
        if doi_parsed.netloc in ["www.doi.org", "doi.org"]:
            if doi_parsed.scheme not in ["https", "http"]:
                raise errors.ValidationError(
                    message=f"Received the right doi.org host but an unexpected scheme {doi_parsed} for doi {doi}."
                )
            doi_clean = doi_parsed.path.strip("/")
        if doi.startswith("doi:"):
            doi_clean = doi[4:]
        if not doi_clean or not DOI.__regex.match(doi_clean):
            raise errors.ValidationError(message=f"The provided value {doi} is not a valid doi.")
        return super().__new__(cls, doi_clean)

    @property
    def url(self) -> str:
        """Return a proper URL from the doi."""
        return f"https://doi.org/{self}"

    async def resolve_host(self) -> str | None:
        """Resolves the DOI and returns the hostname of the url where the redirect leads."""
        clnt = httpx.AsyncClient(timeout=5, follow_redirects=True)
        async with clnt:
            try:
                res = await clnt.get(self.url)
            except httpx.HTTPError:
                return None
        if res.status_code != 200:
            return None
        return res.url.host


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


class SchemaOrgDistribution(BaseModel):
    """The distribution field of a schema.org dataset."""

    model_config = ConfigDict(extra="ignore")
    type: str = Field(alias="@type")
    content_url: str = Field(alias="contentUrl")


class SchemaOrgDataset(BaseModel):
    """A very limited and partial spec of a schema.org Dataset used by Scicat and Envidat."""

    model_config = ConfigDict(extra="ignore")
    distribution: list[SchemaOrgDistribution] = Field(default_factory=list)
    name: str = Field()
    description: str | None = None
    raw_keywords: str = Field(alias="keywords", default="")

    @property
    def keywords(self) -> list[str]:
        """Split the single keywords string into a list."""
        return [i.strip() for i in self.raw_keywords.split(",")]
