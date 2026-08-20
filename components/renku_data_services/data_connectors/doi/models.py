"""Models for DOIs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal, Self
from urllib.parse import urlparse

import httpx
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, PrivateAttr, ValidationError

from renku_data_services.errors import errors

_clnt = httpx.AsyncClient(timeout=5, follow_redirects=True)


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

    @property
    def prefix(self) -> str:
        """The prefix of the doi, i.e. if the doi is 10.7910/DVN/XLX9F8, then the prefix is 10.7910."""
        return self.split("/")[0]

    async def resolve_host(self) -> str | None:
        """Resolves the DOI and returns the hostname of the url where the redirect leads."""
        try:
            res = await _clnt.get(self.url)
        except httpx.HTTPError:
            return None
        if res.status_code != 200:
            return None
        return res.url.host

    async def metadata(self) -> SchemaOrgDataset | None:
        """Get information about the publisher of the DOI."""
        try:
            res = await _clnt.get(self.url, headers={"Accept": "application/vnd.schemaorg.ld+json"})
        except httpx.HTTPError:
            return None
        if res.status_code != 200:
            return None
        try:
            output = SchemaOrgDataset.model_validate_json(res.text)
        except ValidationError:
            return None
        else:
            return output


@dataclass(frozen=True, eq=True, kw_only=True)
class DOIMetadata:
    """Model for DOI metadata."""

    name: str
    description: str
    keywords: list[str]
    expires_at: datetime | None = None


class SchemaOrgDistribution(BaseModel):
    """The distribution field of a schema.org dataset."""

    model_config = ConfigDict(extra="ignore")
    type: str = Field(alias="@type")
    content_url: str = Field(alias="contentUrl")
    name: str | None = None
    expires: datetime | None = None


class SchemaOrgDataset(BaseModel):
    """A very limited and partial spec of a schema.org Dataset used by Scicat, Envidat, doi.org."""

    model_config = ConfigDict(extra="ignore")
    distribution: list[SchemaOrgDistribution] = Field(default_factory=list)
    name: str = Field()
    description: str | None = None
    raw_keywords: str = Field(alias="keywords", default="")
    publisher: SchemaOrgPublisher | None = None
    provider: SchemaOrgProvider | None = None
    _parsed_keywords: list[str] | None = PrivateAttr(default=None, init=False)

    @staticmethod
    def _parse_keywords(val: Any) -> list[str]:
        if isinstance(val, list):
            if not all([isinstance(i, str) for i in val]):
                raise errors.ValidationError(message=f"Cannot parse keywords {val} for Schema.org dataset")
            return [i.strip() for i in val if len(i) > 0]
        elif isinstance(val, str):
            return [i.strip() for i in val.split(",") if len(i) > 0]
        raise errors.ValidationError(message=f"Cannot parse keywords {val} for Schema.org dataset")

    def model_post_init(self, __context: Any) -> None:
        """Run post init cleanup."""
        self._parsed_keywords = self._parse_keywords(self.raw_keywords)

    @property
    def keywords(self) -> list[str]:
        """Split the single keywords string into a list."""
        if self._parsed_keywords is not None:
            return self._parsed_keywords
        self._parsed_keywords = self._parse_keywords(self.raw_keywords)
        return self._parsed_keywords

    @keywords.setter
    def keywords(self, value: list[str]) -> None:
        """Set the keywords."""
        self._parsed_keywords = self._parse_keywords(value)

    def to_doi_metadata(self) -> DOIMetadata:
        """Convert to an alternative metdata representation."""
        return DOIMetadata(
            name=self.name,
            description=self.description or "",
            keywords=self.keywords,
            expires_at=self.expires_at(),
        )

    def expires_at(self) -> datetime | None:
        """Indicates when the dataset expired.

        If there is no expiry date None is returned.
        If there are multiple entries in the distribution then the earliest, non-null entry is returned.
        """
        expiry_dates = [i.expires for i in self.distribution if i.expires is not None]
        earliest_expiry = min(expiry_dates) if len(expiry_dates) > 0 else None
        return earliest_expiry


class SchemaOrgPublisher(BaseModel):
    """The schema.org publisher field in a dataset."""

    model_config = ConfigDict(extra="ignore")
    id: str | None = Field(alias="@id", default=None)
    type: str | None = Field(alias="@type", default=None)
    name: str

    @property
    def url(self) -> str | None:
        """Try to see if the id is a URL, and if so return it."""
        if self.id is None:
            return None
        parsed = urlparse(self.id)
        if not parsed.scheme or not parsed.netloc:
            return None
        if parsed.scheme not in ["http", "https"]:
            return None
        return self.id.rstrip("/")


class SchemaOrgProvider(BaseModel):
    """The schema.org provider field in a dataset."""

    model_config = ConfigDict(extra="ignore")
    type: str | None = Field(alias="@type", default=None)
    name: str


class DOIHandles(BaseModel):
    """The response from the doi handles endpoint."""

    model_config = ConfigDict(extra="ignore")
    values: list[Annotated[DOIHandlesUrl | DOIHandlesUndefined, Field(union_mode="left_to_right")]]

    @property
    def url(self) -> AnyHttpUrl | None:
        """Get the provider url the doi would resolve to."""
        for i in self.values:
            if isinstance(i, DOIHandlesUrl):
                return i.data.value
        return None


class DOIHandlesUrl(BaseModel):
    """The url from the doi handles endpoint."""

    model_config = ConfigDict(extra="ignore")
    type: Literal["URL"]
    data: DOIHandlesUrlData


class DOIHandlesUndefined(BaseModel):
    """Can contain arbitrary data from the doi handles endpoint."""

    model_config = ConfigDict(extra="ignore")
    type: str


class DOIHandlesUrlData(BaseModel):
    """The url from the doi handles endpoint."""

    model_config = ConfigDict(extra="ignore")
    format: Literal["string"]
    value: AnyHttpUrl
