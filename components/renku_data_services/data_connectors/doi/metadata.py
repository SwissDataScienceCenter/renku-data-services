"""Metadata handling for DOIs."""

import httpx
from pydantic import ValidationError as PydanticValidationError

from renku_data_services.data_connectors.doi import models
from renku_data_services.storage.rclone import RCloneDOIMetadata


async def get_dataset_metadata(rclone_metadata: RCloneDOIMetadata) -> models.DOIMetadata | None:
    """Retrieve DOI metadata."""
    if rclone_metadata.provider == "invenio" or rclone_metadata.provider == "zenodo":
        return await _get_dataset_metadata_invenio(rclone_metadata=rclone_metadata)

    return None


async def _get_dataset_metadata_invenio(rclone_metadata: RCloneDOIMetadata) -> models.DOIMetadata | None:
    """Retrieve DOI metadata from the InvenioRDM API."""
    metadata_url = rclone_metadata.metadata_url
    if not metadata_url:
        return None

    async with httpx.AsyncClient(timeout=5) as client:
        try:
            res = await client.get(url=metadata_url, follow_redirects=True, headers=[("accept", "application/json")])
            if res.status_code >= 400:
                return None
            record = models.InvenioRecord.model_validate_json(res.content)
        except httpx.HTTPError:
            return None
        except PydanticValidationError:
            return None

    name = ""
    description = ""
    keywords = []
    if record.metadata is not None:
        name = record.metadata.title or ""
        description = record.metadata.description or ""
        keywords = record.metadata.keywords or []
    return models.DOIMetadata(name=name, description=description, keywords=keywords)
