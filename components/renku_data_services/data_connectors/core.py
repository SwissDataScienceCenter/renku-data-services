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
from renku_data_services.data_connectors import apispec, models
from renku_data_services.data_connectors.constants import ALLOWED_GLOBAL_DATA_CONNECTOR_PROVIDERS
from renku_data_services.data_connectors.doi import schema_org
from renku_data_services.data_connectors.doi.metadata import create_envidat_metadata_url, get_dataset_metadata
from renku_data_services.data_connectors.doi.models import DOI, SchemaOrgDataset
from renku_data_services.storage import models as storage_models
from renku_data_services.storage.constants import ENVIDAT_V1_PROVIDER
from renku_data_services.storage.rclone import RCloneDOIMetadata, RCloneValidator
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


def validate_unsaved_storage_url(
    storage: apispec.CloudStorageUrlV2, validator: RCloneValidator
) -> models.CloudStorageCore:
    """Validate the unsaved storage when its configuration is specificed as a URL."""
    cloud_storage = storage_models.UnsavedCloudStorage.from_url(
        project_id="FAKEPROJECTID",
        name="fake-storage-name",
        storage_url=storage.storage_url,
        target_path=storage.target_path,
        readonly=storage.readonly,
    )
    configuration = cloud_storage.configuration.config
    source_path = cloud_storage.source_path
    validator.validate(configuration)
    return models.CloudStorageCore(
        storage_type=configuration["type"],
        configuration=configuration,
        source_path=source_path,
        target_path=storage.target_path,
        readonly=storage.readonly,
    )


def validate_unsaved_storage_generic(
    storage: apispec.CloudStorageCorePost, validator: RCloneValidator
) -> models.CloudStorageCore:
    """Validate the unsaved storage when its configuration is specificed as a URL."""
    configuration = storage.configuration
    validator.validate(configuration)
    storage_type = configuration.get("type")
    if not isinstance(storage_type, str):
        raise errors.ValidationError()
    return models.CloudStorageCore(
        storage_type=storage_type,
        configuration=configuration,
        source_path=storage.source_path,
        target_path=storage.target_path,
        readonly=storage.readonly,
    )


async def validate_unsaved_storage_doi(
    storage: apispec.CloudStorageCorePost, validator: RCloneValidator
) -> tuple[models.CloudStorageCore, DOI]:
    """Validate the storage configuration of an unsaved data connector."""

    configuration: dict[str, Any]
    source_path: str

    doi_str = storage.configuration.get("doi")
    if not isinstance(doi_str, str):
        raise errors.ValidationError(message="Cannot find the doi in the storage configuration")

    doi = DOI(doi_str)
    doi_host = await doi.resolve_host()

    match doi_host:
        case "envidat.ch" | "www.envidat.ch":
            converted_storage = await convert_envidat_v1_data_connector_to_s3(storage)
            configuration = converted_storage.configuration
            source_path = converted_storage.source_path or "/"
            storage_type = ENVIDAT_V1_PROVIDER
        case _:
            # Most likely supported by rclone doi provider, you have to call validator.get_doi_metadata to confirm
            configuration = storage.configuration
            source_path = storage.source_path or "/"
            storage_type = storage.storage_type or "doi"

    validator.validate(configuration)

    return models.CloudStorageCore(
        storage_type=storage_type,
        configuration=configuration,
        source_path=source_path,
        target_path=storage.target_path,
        readonly=storage.readonly,
    ), doi


async def validate_unsaved_data_connector(
    body: apispec.DataConnectorPost, validator: RCloneValidator
) -> models.UnsavedDataConnector:
    """Validate an unsaved data connector."""

    keywords = [kw.root for kw in body.keywords] if body.keywords is not None else []
    match body.storage:
        case apispec.CloudStorageCorePost() if body.storage.storage_type != "doi":
            storage = validate_unsaved_storage_generic(body.storage, validator=validator)
        case apispec.CloudStorageCorePost() if body.storage.storage_type == "doi":
            storage, _ = await validate_unsaved_storage_doi(body.storage, validator=validator)
        case apispec.CloudStorageUrlV2():
            storage = validate_unsaved_storage_url(body.storage, validator=validator)
        case _:
            raise errors.ValidationError(message="The data connector provided has an unknown payload format.")

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
) -> models.PrevalidatedGlobalDataConnector:
    """Pre-validate an unsaved data connector."""
    # TODO: allow admins to create global data connectors, e.g. s3://giab
    if isinstance(body.storage, apispec.CloudStorageUrlV2):
        raise errors.ValidationError(message="Global data connectors cannot be configured via a URL.")
    storage, doi = await validate_unsaved_storage_doi(body.storage, validator=validator)
    if storage.storage_type not in ALLOWED_GLOBAL_DATA_CONNECTOR_PROVIDERS:
        raise errors.ValidationError(message="Only doi storage type is allowed for global data connectors")
    if not storage.readonly:
        raise errors.ValidationError(message="Global data connectors must be read-only")

    rclone_metadata: RCloneDOIMetadata | None = None
    doi_uri = f"doi:{doi}"
    if storage.storage_type == "doi":
        # This means that the storage is most likely supported by Rclone, by calling the get_doi_metadata we confirm
        rclone_metadata = await validator.get_doi_metadata(configuration=storage.configuration)
        if not rclone_metadata:
            raise errors.ValidationError(message="The provided DOI is not supported.")
        # Override provider in storage config
        storage.configuration["provider"] = rclone_metadata.provider

    slug = base_models.Slug.from_name(doi_uri).value
    doi_metadata = await doi.metadata()
    return models.PrevalidatedGlobalDataConnector(
        data_connector=models.UnsavedGlobalDataConnector(
            name=doi_uri,
            slug=slug,
            visibility=Visibility.PUBLIC,
            created_by="",
            storage=storage,
            description=None,
            keywords=[],
            doi=doi,
            publisher_url=None
            if doi_metadata is None or doi_metadata.publisher is None
            else doi_metadata.publisher.url,
            publisher_name=None
            if doi_metadata is None or doi_metadata.publisher is None
            else doi_metadata.publisher.name,
        ),
        rclone_metadata=rclone_metadata,
    )


async def validate_unsaved_global_data_connector(
    prevalidated_dc: models.PrevalidatedGlobalDataConnector,
    validator: RCloneValidator,
) -> models.UnsavedGlobalDataConnector:
    """Validate the data connector."""
    data_connector = prevalidated_dc.data_connector
    doi = prevalidated_dc.data_connector.doi
    rclone_metadata = prevalidated_dc.rclone_metadata

    if not doi:
        raise errors.ValidationError(message="Global data connectors require a DOI.")

    # Check that we can list the files in the DOI
    connection_result = await validator.test_connection(
        configuration=data_connector.storage.configuration, source_path=data_connector.storage.source_path or "/"
    )
    if not connection_result.success:
        raise errors.ValidationError(
            message="The provided storage configuration is not currently working", detail=connection_result.error
        )

    # Fetch DOI metadata
    if rclone_metadata:
        metadata = await get_dataset_metadata(rclone_metadata.provider, rclone_metadata.metadata_url)
    elif data_connector.storage.storage_type == ENVIDAT_V1_PROVIDER:
        metadata_url = create_envidat_metadata_url(doi)
        metadata = await get_dataset_metadata(ENVIDAT_V1_PROVIDER, metadata_url)
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
    target_path_extension: str | None = None
    with contextlib.suppress(errors.ValidationError):
        target_path_extension = base_models.Slug.from_name(name).value
    # If we were not able to get metadata about the dataset earlier,
    # the slug and the name are essentially both the same and equal to the doi.
    # And if we extend the target_path in this case it just repeats the slug twice.
    # That is why we do the check below to avoid this case and avoid the ugly target path.
    if target_path_extension and target_path != target_path_extension:
        with contextlib.suppress(errors.ValidationError):
            target_path = base_models.Slug.from_name(f"{target_path_extension[:30]}-{target_path}").value

    # Override source_path and target_path
    storage = models.CloudStorageCore(
        storage_type=data_connector.storage.storage_type,
        configuration=data_connector.storage.configuration,
        source_path=data_connector.storage.source_path,
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
        doi=data_connector.doi,
        publisher_name=data_connector.publisher_name,
        publisher_url=data_connector.publisher_url,
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
    """Converts a doi-like configuration for Envidat to S3."""
    config = payload.configuration
    doi = config.get("doi")
    if not isinstance(doi, str):
        if doi is None:
            raise errors.ValidationError(
                message="Cannot get configuration for Envidat data connector because "
                "the doi is missing from the payload."
            )
        raise errors.ValidationError(
            message=f"Cannot get configuration for Envidat data connector because the doi '{doi}' "
            "in the payload is not a string."
        )
    if len(doi) == 0:
        raise errors.ValidationError(
            message="Cannot get configuration for Envidat data connector because the doi is a string with zero length."
        )
    doi = DOI(doi)

    new_config = payload.model_copy(deep=True)
    new_config.configuration = {}

    envidat_url = create_envidat_metadata_url(doi)
    headers = {"accept": "application/json"}

    clnt = httpx.AsyncClient(follow_redirects=True, timeout=5)
    async with clnt:
        res = await clnt.get(envidat_url, headers=headers)
        if res.status_code != 200:
            raise errors.ValidationError(
                message="Cannot get configuration for Envidat data connector because Envidat responded "
                f"with an unexpected {res.status_code} status code at {res.url}.",
                detail=f"Response from envidat: {res.text}",
            )
    dataset = SchemaOrgDataset.model_validate_json(res.text)
    s3_config = schema_org.get_rclone_config(
        dataset,
        schema_org.DatasetProvider.envidat,
    )
    new_config.configuration = dict(s3_config.rclone_config)
    new_config.source_path = s3_config.path
    new_config.storage_type = "s3"
    return new_config
