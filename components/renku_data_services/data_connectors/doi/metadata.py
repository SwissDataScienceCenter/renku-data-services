"""Metadata handling for DOIs."""

import httpx
from pydantic import ValidationError as PydanticValidationError

from renku_data_services.data_connectors.doi import models
from renku_data_services.storage.rclone import RCloneDOIMetadata


async def get_dataset_metadata(rclone_metadata: RCloneDOIMetadata) -> models.DOIMetadata | None:
    """Retrieve DOI metadata."""
    if rclone_metadata.provider == "invenio" or rclone_metadata.provider == "zenodo":
        return await _get_dataset_metadata_invenio(rclone_metadata=rclone_metadata)
    if rclone_metadata.provider == "dataverse":
        return await _get_dataset_metadata_dataverse(rclone_metadata=rclone_metadata)
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


async def _get_dataset_metadata_dataverse(rclone_metadata: RCloneDOIMetadata) -> models.DOIMetadata | None:
    """Retrieve DOI metadata from the Dataverse API."""
    metadata_url = rclone_metadata.metadata_url
    if not metadata_url:
        return None

    async with httpx.AsyncClient(timeout=5) as client:
        try:
            res = await client.get(url=metadata_url, follow_redirects=True, headers=[("accept", "application/json")])
            if res.status_code >= 400:
                return None
            response = models.DataverseDatasetResponse.model_validate_json(res.content)
        except httpx.HTTPError:
            return None
        except PydanticValidationError:
            return None

    if response.status != "OK":
        return None

    name = ""
    description = ""
    keywords: list[str] = []
    if (
        response.data is not None
        and response.data.latest_version is not None
        and response.data.latest_version.metadata_blocks is not None
        and response.data.latest_version.metadata_blocks.citation is not None
    ):
        for field in response.data.latest_version.metadata_blocks.citation.fields:
            if field.type_name == "title" and field.type_class == "primitive" and not field.multiple:
                name = str(field.value)
            if (
                field.type_name == "dsDescription"
                and field.type_class == "compound"
                and field.multiple
                and isinstance(field.value, list)
                and field.value
            ):
                try:
                    description_field = models.DataverseMetadataBlockCitationField.model_validate(
                        field.value[0].get("dsDescriptionValue", dict())
                    )
                    if (
                        description_field.type_name == "dsDescriptionValue"
                        and description_field.type_class == "primitive"
                        and not description_field.multiple
                    ):
                        description = str(description_field.value)
                except AttributeError:
                    pass
                except PydanticValidationError:
                    pass
            if (
                field.type_name == "keyword"
                and field.type_class == "compound"
                and field.multiple
                and isinstance(field.value, list)
            ):
                for value in field.value:
                    try:
                        kw_field = models.DataverseMetadataBlockCitationField.model_validate(
                            value.get("keywordValue", dict())
                        )
                        if (
                            kw_field.type_name == "keywordValue"
                            and kw_field.type_class == "primitive"
                            and not kw_field.multiple
                        ):
                            keywords.append(str(kw_field.value))
                    except AttributeError:
                        pass
                    except PydanticValidationError:
                        pass
    return models.DOIMetadata(name=name, description=description, keywords=keywords)
