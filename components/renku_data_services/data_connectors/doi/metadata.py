"""Metadata handling for DOIs."""

import contextlib
import re
from dataclasses import dataclass
from enum import StrEnum
from html.parser import HTMLParser
from urllib.parse import urlencode

import httpx
from pydantic import AnyHttpUrl
from pydantic import ValidationError as PydanticValidationError

from renku_data_services.data_connectors import apispec
from renku_data_services.data_connectors.doi import models
from renku_data_services.errors import errors
from renku_data_services.storage.constants import ENVIDAT_V1_PROVIDER


def create_envidat_metadata_url(doi: models.DOI) -> str:
    """Create the metadata url for envidat from a DOI."""
    url = "https://envidat.ch/converters-api/internal-dataset/convert/jsonld"
    params = urlencode({"query": doi})
    return f"{url}?{params}"


async def _get_envidat_metadata(metadata_url: str) -> models.SchemaOrgDataset | None:
    """Get metadata about the envidat dataset."""
    clnt = httpx.AsyncClient(follow_redirects=True, timeout=5)
    headers = {"accept": "application/json"}
    async with clnt:
        try:
            res = await clnt.get(metadata_url, headers=headers)
        except httpx.HTTPError:
            return None
    if res.status_code != 200:
        return None
    try:
        parsed_metadata = models.SchemaOrgDataset.model_validate_json(res.text)
    except PydanticValidationError:
        return None
    return parsed_metadata


class DOIProviders(StrEnum):
    """List of supported doi providers."""

    doi = "doi"
    "Supported by Rclone"
    envidat_v1 = ENVIDAT_V1_PROVIDER
    "Only supported by Renku"


@dataclass
class ParsedDOIMetadata:
    """DOI metadata that has been parsed."""

    dataset: models.SchemaOrgDataset
    provider: DOIProviders


def _host_is(host: str, domain: str) -> bool:
    """Check whether host is exactly domain or a subdomain of domain."""
    return host == domain or host.endswith(f".{domain}")


async def get_metadata(doi: models.DOI) -> ParsedDOIMetadata | None:
    """Get metadata for a specific doi."""
    clnt = httpx.AsyncClient(follow_redirects=True, timeout=5)
    res = await clnt.get(f"https://doi.org/api/handles/{doi}", follow_redirects=True)
    if res.status_code != 200:
        return None
    handles_data = models.DOIHandles.model_validate_json(res.text)
    provider = DOIProviders.doi

    match handles_data.url:
        case None:
            dataset = await doi.metadata()
        case AnyHttpUrl(host=None):
            dataset = await doi.metadata()
        case AnyHttpUrl(host=host) if host and _host_is(host, "psi.ch"):
            raise errors.ValidationError(message="Datasets from PSI or SciCat are not supported yet.")
        case AnyHttpUrl(host=host) if host and _host_is(host, "envidat.ch"):
            dataset = await _get_envidat_metadata(create_envidat_metadata_url(doi))
            provider = DOIProviders.envidat_v1
        case AnyHttpUrl(host=host) if host and _host_is(host, "zenodo.org"):
            dataset = await doi.metadata()
        case AnyHttpUrl(host="dataverse.harvard.edu"):
            dataset = await doi.metadata()
        case _:
            dataset = await doi.metadata()

    if dataset is None:
        return None
    description = _html_to_text(dataset.description or "")
    keywords = dataset.keywords

    # Fix metadata if needed
    name = dataset.name or f"doi:{doi}"
    if len(name) > 99:
        name = f"{name[:96]}..."
    if len(description) > 500:
        description = f"{description[:497]}..."
    fixed_keywords: list[str] = []
    for word in keywords:
        for kw in word.strip().split(","):
            with contextlib.suppress(PydanticValidationError):
                fixed_keywords.append(apispec.Keyword.model_validate(kw.strip()).root)
    keywords = fixed_keywords

    dataset.name = name
    dataset.description = description
    dataset.keywords = keywords

    return ParsedDOIMetadata(dataset=dataset, provider=provider)


def _html_to_text(html: str) -> str:
    """Returns the text content of an html snippet."""
    try:
        f = _HTMLToText()
        f.feed(html)
        content = f.text

        # Cleanup whitespace characters
        content = content.strip()
        content = content.strip("\n")
        content = re.sub(" ( )+", " ", content)
        content = re.sub("\n\n(\n)+", "\n\n", content)
        content = re.sub("\n( )+", "\n", content)

        return content
    except Exception:
        return html


class _HTMLToText(HTMLParser):
    """Parses HTML into text content."""

    def __init__(self, *, convert_charrefs: bool = True) -> None:
        super().__init__(convert_charrefs=convert_charrefs)
        self._text = ""

    @property
    def text(self) -> str:
        return self._text

    def handle_data(self, data: str) -> None:
        self._text += data
