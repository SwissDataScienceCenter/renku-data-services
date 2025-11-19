"""Business logic for data connectors."""

import contextlib
import re
from dataclasses import asdict
from datetime import datetime
from html.parser import HTMLParser
from typing import Any

import httpx
from pydantic import ValidationError as PydanticValidationError

from renku_data_services import base_models, errors
from renku_data_services.authz.models import Visibility
from renku_data_services.base_models.core import (
    NamespacePath,
    ProjectPath,
)
from renku_data_services.data_connectors import apispec, models, schema_org_dataset
from renku_data_services.data_connectors.constants import ALLOWED_GLOBAL_DATA_CONNECTOR_PROVIDERS
from renku_data_services.data_connectors.doi.metadata import get_dataset_metadata
from renku_data_services.storage import models as storage_models
from renku_data_services.storage.constants import ENVIDAT_V1_PROVIDER
from renku_data_services.storage.rclone import RCloneValidator
from renku_data_services.utils.core import get_openbis_pat


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


async def validate_unsaved_storage(
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
    elif storage.storage_type == ENVIDAT_V1_PROVIDER:
        converted_storage = await convert_envidat_v1_data_connector_to_s3(storage)
        configuration = converted_storage.configuration
        source_path = converted_storage.source_path
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


async def validate_unsaved_data_connector(
    body: apispec.DataConnectorPost, validator: RCloneValidator
) -> models.UnsavedDataConnector:
    """Validate an unsaved data connector."""

    keywords = [kw.root for kw in body.keywords] if body.keywords is not None else []
    storage = await validate_unsaved_storage(body.storage, validator=validator)

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

    storage = await validate_unsaved_storage(body.storage, validator=validator)
    # TODO: allow admins to create global data connectors, e.g. s3://giab
    if storage.storage_type not in ALLOWED_GLOBAL_DATA_CONNECTOR_PROVIDERS:
        raise errors.ValidationError(
            message=f"Only {ALLOWED_GLOBAL_DATA_CONNECTOR_PROVIDERS} storage type is allowed for global data connectors"
        )
    if not storage.readonly:
        raise errors.ValidationError(message="Global data connectors must be read-only")

    match storage.storage_type:
        case "doi":
            rclone_metadata = await validator.get_doi_metadata(configuration=storage.configuration)

            doi_uri = f"doi:{rclone_metadata.doi}"
            slug = base_models.Slug.from_name(doi_uri).value

            # Override provider in storage config
            storage.configuration["provider"] = rclone_metadata.provider
        case x if x == ENVIDAT_V1_PROVIDER:
            if not isinstance(body.storage, apispec.CloudStorageCorePost):
                raise errors.ValidationError()
            doi = body.storage.configuration.get("doi")
            if not doi:
                raise errors.ValidationError()
            doi_uri = f"doi:{doi}"
            slug = base_models.Slug.from_name(doi_uri).value
        case x:
            raise errors.ValidationError(
                message=f"Only {ALLOWED_GLOBAL_DATA_CONNECTOR_PROVIDERS} storage type is allowed "
                "for global data connectors"
            )

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
    if data_connector.storage.storage_type == "doi":
        rclone_metadata = await validator.get_doi_metadata(configuration=data_connector.storage.configuration)
        metadata = await get_dataset_metadata(rclone_metadata=rclone_metadata)
    else:
        metadata = None

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


async def openbis_transform_session_token_to_pat(
    unsaved_secrets: list[models.DataConnectorSecretUpdate], openbis_host: str
) -> tuple[list[models.DataConnectorSecretUpdate], datetime]:
    """Transforms a openBIS session to a openBIS personal access token (PAT)."""

    if len(unsaved_secrets) == 1 and unsaved_secrets[0].name == "session_token":
        if unsaved_secrets[0].value is not None:
            try:
                openbis_pat = await get_openbis_pat(openbis_host, unsaved_secrets[0].value)
                return (
                    [models.DataConnectorSecretUpdate(name="pass", value=openbis_pat[0])],
                    openbis_pat[1],
                )
            except Exception as e:
                raise errors.ProgrammingError(message=str(e)) from e
        raise errors.ValidationError(message="The openBIS session token must be a string value.")

    raise errors.ValidationError(message="The openBIS storage has only one secret: session_token")


async def transform_secrets_for_back_end(
    unsaved_secrets: list[models.DataConnectorSecretUpdate], storage: models.CloudStorageCore
) -> tuple[list[models.DataConnectorSecretUpdate], datetime | None]:
    """Transforms the structure of secrets so that the back end can handle them."""
    expiration_timestamp = None
    if storage.storage_type == "openbis":
        (
            unsaved_secrets,
            expiration_timestamp,
        ) = await openbis_transform_session_token_to_pat(unsaved_secrets, storage.configuration["host"])
    return unsaved_secrets, expiration_timestamp


def transform_secrets_for_front_end(
    secrets: list[models.DataConnectorSecret], storage: models.CloudStorageCore
) -> list[models.DataConnectorSecret]:
    """Transforms the structure of secrets so that the front end can handle them."""

    if storage.storage_type == "openbis":
        for i, secret in enumerate(secrets):
            if secret.name == "pass":
                secrets[i] = models.DataConnectorSecret(
                    name="session_token",
                    user_id=secret.user_id,
                    data_connector_id=secret.data_connector_id,
                    secret_id=secret.secret_id,
                )
                break
    return secrets


async def convert_envidat_v1_data_connector_to_s3(
    payload: apispec.CloudStorageCorePost,
) -> apispec.CloudStorageCorePost:
    """Converts a doi-like configuration for Envidat to S3.

    If the paylaod that is passed in is not of the expected type nothing is changed
    and the same payload that was passed in is returned.
    """
    config = payload.configuration
    if config.get("type") != ENVIDAT_V1_PROVIDER:
        return payload

    doi = config.get("doi")
    if not isinstance(doi, str):
        raise errors.ValidationError()
    if len(doi) == 0:
        raise errors.ValidationError()
    doi = doi.removeprefix("https://")
    doi = doi.removeprefix("http://")

    new_config = payload.model_copy(deep=True)
    new_config.configuration = {}

    envidat_url = "https://envidat.ch/converters-api/internal-dataset/convert/jsonld"
    query_params = {"query": doi}
    headers = {"accept": "application/json"}

    clnt = httpx.AsyncClient(follow_redirects=True)
    async with clnt:
        res = await clnt.get(envidat_url, params=query_params, headers=headers)
        if res.status_code != 200:
            raise errors.ProgrammingError()
    dataset = schema_org_dataset.Dataset.model_validate_strings(res.text)
    s3_config = schema_org_dataset.get_rclone_config(
        dataset,
        schema_org_dataset.DatasetProvider.envidat,
    )
    new_config.configuration = dict(s3_config.rclone_config)
    new_config.source_path = s3_config.path
    new_config.storage_type = "s3"
    return new_config
