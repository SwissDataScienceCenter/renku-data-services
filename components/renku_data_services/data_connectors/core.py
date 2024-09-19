"""Business logic for data connectors."""

from dataclasses import asdict
from typing import Any

from renku_data_services import base_models
from renku_data_services.authz.models import Visibility
from renku_data_services.data_connectors import apispec, models
from renku_data_services.storage import models as storage_models
from renku_data_services.storage.rclone import RCloneValidator


def dump_storage_with_sensitive_fields(
    storage: models.CloudStorageCore, validator: RCloneValidator
) -> models.CloudStorageCoreWithSensitiveFields:
    """Add sensitive fields to a storage configuration."""
    return models.CloudStorageCoreWithSensitiveFields(
        sensitive_fields=list(validator.get_private_fields(storage.configuration)), **asdict(storage)
    )


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

    return models.UnsavedDataConnector(
        name=body.name,
        namespace=body.namespace,
        slug=body.slug or base_models.Slug.from_name(body.name).value,
        visibility=Visibility(body.visibility.value),
        created_by="",
        storage=storage,
        description=body.description,
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
    data_connector: models.DataConnector,
    patch: apispec.DataConnectorPatch,
    validator: RCloneValidator,
) -> models.DataConnectorPatch:
    """Validate the update to a data connector."""

    keywords = [kw.root for kw in patch.keywords] if patch.keywords is not None else None
    storage = (
        validate_storage_patch(data_connector.storage, patch.storage, validator=validator)
        if patch.storage is not None
        else None
    )

    return models.DataConnectorPatch(
        name=patch.name,
        namespace=patch.namespace,
        slug=patch.slug,
        visibility=Visibility(patch.visibility.value) if patch.visibility is not None else None,
        description=patch.description,
        keywords=keywords,
        storage=storage,
    )
