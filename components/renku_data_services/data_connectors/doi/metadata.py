"""Metadata handling for DOIs."""

from urllib.parse import urlencode

import httpx
from pydantic import AnyHttpUrl
from pydantic import ValidationError as PydanticValidationError

from renku_data_services.data_connectors.doi import models


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


async def get_metadata(doi: models.DOI) -> models.SchemaOrgDataset | None:
    """Get metadata for a specific doi."""
    clnt = httpx.AsyncClient(follow_redirects=True, timeout=5)
    res = await clnt.get(f"https://doi.org/api/handles/{doi}", follow_redirects=True)
    if res.status_code != 200:
        return None
    handles_data = models.DOIHandles.model_validate_json(res.text)

    match handles_data.url:
        case None:
            dataset = await doi.metadata()
        case AnyHttpUrl(host=None):
            dataset = await doi.metadata()
        case AnyHttpUrl(host=host) if host and host.endswith("psi.ch"):
            raise NotImplementedError()
        case AnyHttpUrl(host=host) if host and host.endswith("envidat.ch"):
            dataset = await _get_envidat_metadata(create_envidat_metadata_url(doi))
        case AnyHttpUrl(host=host) if host and host.endswith("zenodo.org"):
            dataset = await doi.metadata()
        case AnyHttpUrl(host="dataverse.harvard.ch"):
            dataset = await doi.metadata()
        case _:
            dataset = await doi.metadata()

    return dataset
