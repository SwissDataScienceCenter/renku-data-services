"""Business logic for data connectors."""

import contextlib
import re
from dataclasses import asdict
from html.parser import HTMLParser
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from renku_data_services import base_models, errors
from renku_data_services.authz.models import Visibility
from renku_data_services.base_models.core import (
    NamespacePath,
    ProjectPath,
)
from renku_data_services.data_connectors import apispec, models
from renku_data_services.data_connectors.doi.metadata import get_dataset_metadata
from renku_data_services.storage import models as storage_models
from renku_data_services.storage.rclone import RCloneValidator


def dump_storage_with_sensitive_fields(
    storage: models.CloudStorageCore, validator: RCloneValidator
) -> models.CloudStorageCoreWithSensitiveFields:
    """Add sensitive fields to a storage configuration."""
    try:
        body = models.CloudStorageCoreWithSensitiveFields(
            sensitive_fields=[
                apispec.RCloneOption.model_validate(option.model_dump(exclude_none=True, by_alias=True))
                for option in validator.get_private_fields(storage.configuration)
            ],
            **asdict(storage),
        )
    except PydanticValidationError as err:
        parts = [".".join(str(i) for i in field["loc"]) + ": " + field["msg"] for field in err.errors()]
        message = (
            f"The server could not construct a valid response. Errors found in the following fields: {', '.join(parts)}"
        )
        raise errors.ProgrammingError(message=message) from err
    return body


def validate_unsaved_storage(
    storage: apispec.CloudStorageCorePost | apispec.CloudStorageUrlV2, validator: RCloneValidator
) -> models.CloudStorageCore:
    """Validate the storage configuration of an unsaved data connector."""

    configuration: dict[str, Any]
    source_path: str

    if isinstance(storage, apispec.CloudStorageUrlV2):
        cloud_storage = storage_models.UnsavedCloudStorage.from_url(
            project_id="FAKEPROJECTID",
            name="fake-storage-name",
            storage_url=storage.storage_url,
            target_path=storage.target_path,
            readonly=storage.readonly,
        )
        configuration = cloud_storage.configuration.config
        source_path = cloud_storage.source_path
    else:
        configuration = storage.configuration
        source_path = storage.source_path

    validator.validate(configuration)

    return models.CloudStorageCore(
        storage_type=configuration["type"],
        configuration=configuration,
        source_path=source_path,
        target_path=storage.target_path,
        readonly=storage.readonly,
    )


def validate_unsaved_data_connector(
    body: apispec.DataConnectorPost, validator: RCloneValidator
) -> models.UnsavedDataConnector:
    """Validate an unsaved data connector."""

    keywords = [kw.root for kw in body.keywords] if body.keywords is not None else []
    storage = validate_unsaved_storage(body.storage, validator=validator)

    if body.namespace is None:
        raise NotImplementedError("Missing namespace not supported")

    slugs = body.namespace.split("/")
    path: NamespacePath | ProjectPath
    if len(slugs) == 1:
        path = NamespacePath.from_strings(*slugs)
    elif len(slugs) == 2:
        path = ProjectPath.from_strings(*slugs)
    else:
        raise errors.ValidationError(
            message=f"Got an unexpected number of slugs in the namespace for a data connector {slugs}"
        )

    return models.UnsavedDataConnector(
        name=body.name,
        namespace=path,
        slug=body.slug or base_models.Slug.from_name(body.name).value,
        visibility=Visibility(body.visibility.value),
        created_by="",
        storage=storage,
        description=body.description,
        keywords=keywords,
    )


async def prevalidate_unsaved_global_data_connector(
    body: apispec.GlobalDataConnectorPost, validator: RCloneValidator
) -> models.UnsavedGlobalDataConnector:
    """Pre-validate an unsaved data connector."""

    storage = validate_unsaved_storage(body.storage, validator=validator)
    # TODO: allow admins to create global data connectors, e.g. s3://giab
    if storage.storage_type != "doi":
        raise errors.ValidationError(message="Only doi storage type is allowed for global data connectors")
    if not storage.readonly:
        raise errors.ValidationError(message="Global data connectors must be read-only")

    rclone_metadata = await validator.get_doi_metadata(configuration=storage.configuration)

    doi_uri = f"doi:{rclone_metadata.doi}"
    slug = base_models.Slug.from_name(doi_uri).value

    # Override provider in storage config
    storage.configuration["provider"] = rclone_metadata.provider

    return models.UnsavedGlobalDataConnector(
        name=doi_uri,
        slug=slug,
        visibility=Visibility.PUBLIC,
        created_by="",
        storage=storage,
        description=None,
        keywords=[],
    )


async def validate_unsaved_global_data_connector(
    data_connector: models.UnsavedGlobalDataConnector,
    validator: RCloneValidator,
) -> models.UnsavedGlobalDataConnector:
    """Validate an unsaved data connector."""

    # Check that we can list the files in the DOI
    connection_result = await validator.test_connection(
        configuration=data_connector.storage.configuration, source_path="/"
    )
    if not connection_result.success:
        raise errors.ValidationError(
            message="The provided storage configuration is not currently working", detail=connection_result.error
        )

    # Fetch DOI metadata
    rclone_metadata = await validator.get_doi_metadata(configuration=data_connector.storage.configuration)
    metadata = await get_dataset_metadata(rclone_metadata=rclone_metadata)

    name = data_connector.name
    description = ""
    keywords: list[str] = []
    if metadata is not None:
        name = metadata.name or name
        description = _html_to_text(metadata.description)
        keywords = metadata.keywords

    # Fix metadata if needed
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

    # Assign user-friendly target_path if possible
    target_path = data_connector.slug
    with contextlib.suppress(errors.ValidationError):
        name_slug = base_models.Slug.from_name(name).value
        target_path = base_models.Slug.from_name(f"{name_slug[:30]}-{target_path}").value

    # Override source_path and target_path
    storage = models.CloudStorageCore(
        storage_type=data_connector.storage.storage_type,
        configuration=data_connector.storage.configuration,
        source_path="/",
        target_path=target_path,
        readonly=data_connector.storage.readonly,
    )

    return models.UnsavedGlobalDataConnector(
        name=name,
        slug=data_connector.slug,
        visibility=Visibility.PUBLIC,
        created_by="",
        storage=storage,
        description=description or None,
        keywords=keywords,
    )


def validate_storage_patch(
    storage: models.CloudStorageCore, patch: apispec.CloudStorageCorePatch, validator: RCloneValidator
) -> models.CloudStorageCorePatch:
    """Validate the update to a data connector's storage."""

    if patch.configuration is not None:
        # we need to apply the patch to the existing storage to properly validate it
        patch.configuration = {**storage.configuration, **patch.configuration}
        dict_items = list(patch.configuration.items())
        for k, v in dict_items:
            if v is None:
                # delete fields that were unset
                del patch.configuration[k]
        validator.validate(patch.configuration)

    return models.CloudStorageCorePatch(
        storage_type=patch.storage_type,
        configuration=patch.configuration,
        source_path=patch.source_path,
        target_path=patch.target_path,
        readonly=patch.readonly,
    )


def validate_data_connector_patch(
    data_connector: models.DataConnector | models.GlobalDataConnector,
    patch: apispec.DataConnectorPatch,
    validator: RCloneValidator,
) -> models.DataConnectorPatch:
    """Validate the update to a data connector."""
    if isinstance(data_connector, models.GlobalDataConnector) and patch.namespace is not None:
        raise errors.ValidationError(message="Assigning a namespace to a global data connector is not supported")
    if (
        isinstance(data_connector, models.GlobalDataConnector)
        and patch.slug is not None
        and patch.slug != data_connector.slug
    ):
        raise errors.ValidationError(message="Updating the slug of a global data connector is not supported")

    slugs = patch.namespace.split("/") if patch.namespace else []
    path: NamespacePath | ProjectPath | None
    if len(slugs) == 0:
        path = None
    elif len(slugs) == 1:
        path = NamespacePath.from_strings(*slugs)
    elif len(slugs) == 2:
        path = ProjectPath.from_strings(*slugs)
    else:
        raise errors.ValidationError(
            message="Trying to create a data connector with more than invalid number of slugs in its namespace"
        )

    keywords = [kw.root for kw in patch.keywords] if patch.keywords is not None else None
    storage = (
        validate_storage_patch(data_connector.storage, patch.storage, validator=validator)
        if patch.storage is not None
        else None
    )

    return models.DataConnectorPatch(
        name=patch.name,
        namespace=path,
        slug=patch.slug,
        visibility=Visibility(patch.visibility.value) if patch.visibility is not None else None,
        description=patch.description,
        keywords=keywords,
        storage=storage,
    )


def validate_data_connector_secrets_patch(
    put: apispec.DataConnectorSecretPatchList,
) -> list[models.DataConnectorSecretUpdate]:
    """Validate the update to a data connector's secrets."""
    seen_names: set[str] = set()
    for secret in put.root:
        if secret.name in seen_names:
            raise errors.ValidationError(message=f"Found duplicate name '{secret.name}' in the list of secrets.")
        seen_names.add(secret.name)

    return [
        models.DataConnectorSecretUpdate(
            name=secret.name,
            value=secret.value,
        )
        for secret in put.root
    ]


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
