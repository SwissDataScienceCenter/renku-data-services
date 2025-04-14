"""Business logic for data connectors."""

from dataclasses import asdict
from typing import Any
from urllib.parse import urlparse

from pydantic import ValidationError as PydanticValidationError

from renku_data_services import base_models, errors
from renku_data_services.authz.models import Visibility
from renku_data_services.base_models.core import (
    NamespacePath,
    ProjectPath,
)
from renku_data_services.data_connectors import apispec, models
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


async def validate_unsaved_global_data_connector(
    body: apispec.GlobalDataConnectorPost, validator: RCloneValidator
) -> models.UnsavedGlobalDataConnector:
    """Validate an unsaved data connector."""

    storage = validate_unsaved_storage(body.storage, validator=validator)
    if storage.storage_type != "doi":
        raise errors.ValidationError(message="Only doi storage type is allowed for global data connectors")
    if not storage.readonly:
        raise errors.ValidationError(message="Global data connectors must be read-only")

    # Check that we can list the files in the DOI
    connection_result = await validator.test_connection(configuration=storage.configuration, source_path="/")
    if not connection_result.success:
        raise errors.ValidationError(
            message="The provided storage configuration is not currently working", detail=connection_result.error
        )

    doi = _validate_doi(str(storage.configuration.get("doi")))
    if not doi:
        raise errors.ValidationError(message="Missing doi in the storage configuration")
    name = f"doi:{doi}"
    slug = base_models.Slug.from_name(name).value

    # Override source_path and target_path
    storage = models.CloudStorageCore(
        storage_type=storage.storage_type,
        configuration=storage.configuration,
        source_path="/",
        target_path=slug,
        readonly=storage.readonly,
    )

    return models.UnsavedGlobalDataConnector(
        name=name,
        slug=slug,
        visibility=Visibility.PUBLIC,
        created_by="",
        storage=storage,
        description=None,
        keywords=[],
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


def _validate_doi(doi: str) -> str:
    """Validate a DOI."""
    doi = doi.lower()
    if doi.startswith("doi:"):
        return doi[len("doi:") :]
    parsed = urlparse(doi)
    if parsed.hostname is not None and parsed.hostname.endswith("doi.org"):
        path = parsed.path
        return path[1:] if path.startswith("/") else path
    return doi
