"""Business logic for data connectors."""

from __future__ import annotations

import base64
import contextlib
import re
from collections.abc import AsyncIterator
from dataclasses import asdict
from datetime import datetime
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

import httpx
import kubernetes
from kubernetes.client import (
    V1Capabilities,
    V1Container,
    V1EnvFromSource,
    V1EnvVar,
    V1Job,
    V1JobSpec,
    V1JobStatus,
    V1ObjectMeta,
    V1OwnerReference,
    V1PersistentVolumeClaim,
    V1PersistentVolumeClaimSpec,
    V1PersistentVolumeClaimVolumeSource,
    V1PodSpec,
    V1PodTemplateSpec,
    V1Secret,
    V1SecretEnvSource,
    V1SecurityContext,
    V1Volume,
    V1VolumeMount,
    V1VolumeResourceRequirements,
)
from pydantic import ValidationError as PydanticValidationError
from sanic import Request
from ulid import ULID

from renku_data_services import base_models, errors
from renku_data_services.authz.models import Visibility
from renku_data_services.base_models.core import (
    NamespacePath,
    ProjectPath,
)
from renku_data_services.data_connectors import apispec, models
from renku_data_services.data_connectors.config import DepositConfig
from renku_data_services.data_connectors.constants import ALLOWED_GLOBAL_DATA_CONNECTOR_PROVIDERS
from renku_data_services.data_connectors.doi import schema_org
from renku_data_services.data_connectors.doi.metadata import create_envidat_metadata_url, get_dataset_metadata
from renku_data_services.data_connectors.doi.models import DOI, SchemaOrgDataset
from renku_data_services.k8s.client_interfaces import K8sClient
from renku_data_services.k8s.clients import DepositUploadJobClient
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER, ClusterId
from renku_data_services.k8s.models import GVK, K8sObject, K8sObjectMeta
from renku_data_services.notebooks.data_sources import DataSourceRepository
from renku_data_services.storage import models as storage_models
from renku_data_services.storage.constants import ENVIDAT_V1_PROVIDER
from renku_data_services.storage.rclone import RCloneDOIMetadata, RCloneValidator
from renku_data_services.utils.core import get_openbis_pat

if TYPE_CHECKING:
    from renku_data_services.data_connectors.db import DataConnectorRepository, DataConnectorSecretRepository

sanitizer = kubernetes.client.ApiClient().sanitize_for_serialization


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


def validate_deposit(body: apispec.DepositPost, original_id: str) -> models.UnsavedDepositJob:
    """Validate the payload to creation of a deposit."""
    dc_id = ULID.from_str(body.data_connector_id)
    dep = models.UnsavedDeposit(
        data_connector_id=dc_id,
        original_id=original_id,
        source=models.DepositSource(body.provider.value),
        path=PurePosixPath(body.path) if body.path else None,
        status=models.DepositStatus.in_progress,
        name=body.name,
    )
    job_name = "deposit-" + str(ULID()).lower()
    return models.UnsavedDepositJob(
        name=job_name,
        cluster_id=DEFAULT_K8S_CLUSTER,
        deposit=dep,
    )


def validate_deposit_patch(body: apispec.DepositPatch) -> models.DepositPatch:
    """Validate the payload to patching of a deposit."""
    status: models.DepositStatus | None = None
    if body.status:
        status = models.DepositStatus(body.status.value)
    return models.DepositPatch(
        name=body.name, status=status, path=PurePosixPath(body.path) if body.path is not None else None
    )


def serialize_deposit(deposit: models.DepositJob) -> dict[str, Any]:
    """Create an apispec Deposit from the internal model."""
    return dict(
        name=deposit.deposit.name,
        provider=deposit.deposit.source.value,
        data_connector_id=str(deposit.deposit.data_connector_id),
        path=deposit.deposit.path.as_posix() if deposit.deposit.path else "/",
        id=str(deposit.deposit.id),
        status=deposit.deposit.status.value,
        external_url=f"https://zenodo.org/uploads/{deposit.deposit.original_id}",
        creation_date=deposit.deposit.creation_date,
        updated_at=deposit.deposit.updated_at,
        etag=deposit.etag,
    )


async def create_deposit_upload(
    request: Request,
    user: base_models.AuthenticatedAPIUser,
    deposit_config: DepositConfig,
    storage_class: str,
    k8s_client: K8sClient,
    data_service_base_url: str,
    deposit_job: models.DepositJob,
    job_client: DepositUploadJobClient,
    deposit_api_key: str,
    data_source_repo: DataSourceRepository,
    data_connector_repo: DataConnectorRepository,
    data_connector_secret_repo: DataConnectorSecretRepository,
) -> None:
    """Create the resources required to upload data to a deposit."""

    def _convert_to_k8s_object(
        input: V1Job | V1Secret | V1PersistentVolumeClaim, cluster_id: ClusterId, user_id: str
    ) -> K8sObject:
        if not isinstance(input.metadata, V1ObjectMeta):
            raise errors.ProgrammingError(message="Cannot convert a k8s object that is missing metadata.")
        match input:
            case V1Job():
                gvk = GVK(kind="Job", version="v1", group="batch")
            case V1Secret():
                gvk = GVK(kind="Secret", version="v1")
            case V1PersistentVolumeClaim():
                gvk = GVK(kind="PersistentVolumeClaim", version="v1")
            case x:
                raise errors.ProgrammingError(
                    message=f"Unexpected reosurce type {x.api_version}-{x.kind} when creating converting k8s object"
                )

        return K8sObject(
            name=input.metadata.name,
            namespace=input.metadata.namespace,
            cluster=cluster_id,
            gvk=gvk,
            manifest=sanitizer(input),
            user_id=user_id,
        )

    def _create_secret_manifest(
        name: str,
        namespace: str,
        data: dict[str, str],
        owner_ref: V1OwnerReference | None = None,
        labels: dict[str, str] | None = None,
    ) -> V1Secret:
        return V1Secret(
            metadata=V1ObjectMeta(
                name=name,
                namespace=namespace,
                labels=labels,
                owner_references=[owner_ref] if owner_ref else None,
            ),
            type="Opaque",
            data={k: base64.b64encode(v.encode()).decode() for k, v in data.items()},
        )

    def _create_deposit_upload_job_manifest(
        deposit_config: DepositConfig,
        deposit_job: models.DepositJob,
        api_key_secret_name: str,
        work_dir: PurePosixPath,
        pvc_name: str,
        labels: dict[str, str] | None = None,
        suspended: bool = False,
    ) -> V1Job:
        mount_path = PurePosixPath("/" + pvc_name)
        copy_source = mount_path
        if deposit_job.deposit.path is not None:
            copy_source = mount_path / (
                deposit_job.deposit.path.relative_to("/")
                if deposit_job.deposit.path.is_absolute()
                else deposit_job.deposit.path
            )
        return V1Job(
            metadata=V1ObjectMeta(
                name=deposit_job.name,
                namespace=deposit_config.namespace,
                labels=labels,
            ),
            spec=V1JobSpec(
                backoff_limit=0,  # create only 1 pod, dont keep creating new pods on failure
                ttl_seconds_after_finished=3600 * 6,  # will clean itself up after 6 hrs, also will cleanup all children
                suspend=suspended,
                template=V1PodTemplateSpec(
                    metadata=V1ObjectMeta(labels=labels),
                    spec=V1PodSpec(
                        restart_policy="Never",
                        tolerations=deposit_config.tolerations,
                        node_selector=deposit_config.node_selector,
                        containers=[
                            V1Container(
                                security_context=V1SecurityContext(
                                    privileged=False,
                                    run_as_non_root=True,
                                    capabilities=V1Capabilities(drop=["ALL"]),
                                    run_as_user=1000,
                                    run_as_group=1000,
                                ),
                                name="upload-deposit",
                                image=deposit_config.image,
                                env_from=[V1EnvFromSource(secret_ref=V1SecretEnvSource(name=api_key_secret_name))],
                                env=[
                                    V1EnvVar(name="RUST_LOG", value="info"),
                                    V1EnvVar(name="RENKU_CLI_RENKU_URL", value=deposit_config.renku_url),
                                    V1EnvVar(name="ZENODO_URL", value=deposit_config.zenodo_url),
                                ],
                                args=[
                                    "dataset",
                                    "deposit",
                                    "cp",
                                    copy_source.as_posix(),
                                    deposit_job.deposit.original_id,
                                ],
                                working_dir=work_dir.as_posix(),
                                volume_mounts=[
                                    V1VolumeMount(mount_path=mount_path.as_posix(), read_only=True, name=pvc_name)
                                ],
                            )
                        ],
                        volumes=[
                            V1Volume(
                                name=pvc_name,
                                persistent_volume_claim=V1PersistentVolumeClaimVolumeSource(
                                    claim_name=pvc_name,
                                    read_only=True,
                                ),
                            )
                        ],
                    ),
                ),
            ),
        )

    def _create_pvc_manifest(
        name: str,
        namespace: str,
        storage_class: str,
        access_mode: str,
        owner_ref: V1OwnerReference,
        credentials_secret_name: str | None,
        labels: dict[str, str] | None = None,
    ) -> V1PersistentVolumeClaim:
        annotations = {}
        if credentials_secret_name:
            annotations["csi-rclone.dev/secretName"] = credentials_secret_name
        return V1PersistentVolumeClaim(
            metadata=V1ObjectMeta(
                name=name,
                namespace=namespace,
                labels=labels,
                annotations=annotations,
                owner_references=[owner_ref],
            ),
            spec=V1PersistentVolumeClaimSpec(
                access_modes=[access_mode],
                storage_class_name=storage_class,
                resources=V1VolumeResourceRequirements(requests={"storage": "1Gi"}),
            ),
        )

    def _get_owner_reference(job: V1Job) -> V1OwnerReference:
        if not isinstance(job.metadata, V1ObjectMeta):
            raise errors.ProgrammingError()
        return V1OwnerReference(
            name=job.metadata.name,
            api_version=job.api_version,
            block_owner_deletion=False,
            controller=False,
            uid=job.metadata.uid,
            kind=job.kind,
        )

    async def _request_saved_secret_creation(
        user: base_models.AuthenticatedAPIUser,
        data_service_base_url: str,
        dc_secrets_dict: dict[str, list[models.DataConnectorSecret]],
        deposit_config: DepositConfig,
        pvc_name: str,
        owner_reference: V1OwnerReference,
    ) -> K8sObjectMeta | None:
        """Calls the secret service to request the creation of saved storage secrets."""
        secrets_url = data_service_base_url + "/api/secrets/kubernetes"
        headers = {"Authorization": f"bearer {user.access_token}"}
        dc_secrets = list(dc_secrets_dict.items())
        if len(dc_secrets) > 0:
            s_id, secrets = dc_secrets[0]
        else:
            s_id = None
            secrets = None
        if s_id is not None and secrets is not None and len(secrets) > 0:
            # NOTE: The name of this secret has to be the PVC name + "-secrets"
            # That is what CSI rclone expects
            secret_name = f"{pvc_name}-secrets"
            request_data = {
                "name": secret_name,
                "namespace": deposit_config.namespace,
                "secret_ids": [str(secret.secret_id) for secret in secrets],
                "owner_references": [sanitizer(owner_reference)],
                "key_mapping": {str(secret.secret_id): secret.name for secret in secrets},
                "cluster_id": str(deposit_config.cluster_id),
            }
            async with httpx.AsyncClient(timeout=10) as client:
                res = await client.post(secrets_url, headers=headers, json=request_data)
            if res.status_code >= 300 or res.status_code < 200:
                raise errors.ProgrammingError(
                    message=f"The secret for data connector with {s_id} could not be "
                    f"successfully created, the status code was {res.status_code}."
                    "Please contact a Renku administrator.",
                    detail=res.text,
                )
            return K8sObjectMeta(
                name=secret_name,
                cluster=deposit_config.cluster_id,
                gvk=GVK(version="V1", kind="Secret"),
                namespace=deposit_config.namespace,
            )

        return None

    def _storage_config_secret_manifest(
        secret: V1Secret,
        owner_reference: V1OwnerReference,
        pvc_name: str,
        labels: dict[str, str],
        deposit_config: DepositConfig,
    ) -> K8sObject:
        manifest = sanitizer(secret)
        manifest["metadata"]["ownerReferences"] = [sanitizer(owner_reference)]
        manifest["metadata"]["name"] = pvc_name
        manifest["metadata"]["labels"] = labels
        return K8sObject(
            name=pvc_name,
            namespace=deposit_config.namespace,
            cluster=deposit_config.cluster_id,
            gvk=GVK(kind="Secret", version="v1"),
            manifest=manifest,
        )

    dc = await data_connector_repo.get_data_connector(
        user=user, data_connector_id=deposit_job.deposit.data_connector_id
    )
    dc_config_secrets = await data_connector_secret_repo.get_data_connector_secrets(user, dc.id)

    async def dc_iter() -> AsyncIterator[models.DataConnectorWithSecrets]:
        yield dc.with_secrets(dc_config_secrets)

    extras = await data_source_repo.get_data_sources(
        request=request,
        user=user,
        resource_type="deposit_job",
        base_name=deposit_job.name,
        data_connectors_stream=dc_iter(),
        work_dir=PurePosixPath(),
        data_connectors_overrides=[],
        namespace=deposit_config.namespace,
        storage_class=storage_class,
    )

    assert len(extras.containers) == 0
    assert len(extras.init_containers) == 0
    assert len(extras.volume_mounts) == 0
    assert len(extras.volumes) == 0
    # If the data connector has a saved credential then the credentials are in a secret in data_connector_secrets
    assert len(extras.data_connector_secrets) <= 1
    # The regular non-secret rclone config is in secrets
    assert len(extras.secrets) == 1
    assert len(extras.data_sources) == 1
    data_src = extras.data_sources[0]

    base_name = deposit_job.name
    pvc_name = deposit_job.name + "-ds"
    # NOTE: The user id label is important - that is how authorization is enforced
    # TODO: Cleanup user-id authorization - add it in the k8s client
    labels = {"renku.io/deposit_id": str(deposit_job.deposit.id), "renku.io/safe-username": user.id}

    work_dir = PurePosixPath("/work")

    job = _create_deposit_upload_job_manifest(
        deposit_config=deposit_config,
        deposit_job=deposit_job,
        api_key_secret_name=base_name,
        work_dir=work_dir,
        suspended=True,
        labels=labels,
        pvc_name=pvc_name,
    )
    created_job = await job_client.create(
        _convert_to_k8s_object(job, cluster_id=deposit_config.cluster_id, user_id=user.id)
    )
    owner_reference = _get_owner_reference(created_job)

    resources_to_create: list[K8sObject] = []
    created_objects: list[K8sObjectMeta] = [
        _convert_to_k8s_object(created_job, cluster_id=deposit_config.cluster_id, user_id=user.id)
    ]

    job_secret = _create_secret_manifest(
        name=base_name,
        namespace=deposit_config.namespace,
        data={"ZENODO_API_KEY": deposit_api_key},
        labels=labels,
        owner_ref=owner_reference,
    )
    resources_to_create.append(
        _convert_to_k8s_object(job_secret, cluster_id=deposit_config.cluster_id, user_id=user.id)
    )

    pvc = _create_pvc_manifest(
        name=pvc_name,
        namespace=deposit_config.namespace,
        storage_class=storage_class,
        access_mode=data_src.accessMode,
        owner_ref=owner_reference,
        credentials_secret_name=pvc_name,
        labels=labels,
    )
    resources_to_create.append(_convert_to_k8s_object(pvc, cluster_id=deposit_config.cluster_id, user_id=user.id))

    # Create the secret manifest that contains the unencrypted rclone config
    storage_config_secret = _storage_config_secret_manifest(
        extras.secrets[0].secret,
        owner_reference=owner_reference,
        pvc_name=pvc_name,
        labels=labels,
        deposit_config=deposit_config,
    )
    resources_to_create.append(storage_config_secret)

    # Request the creation of saved encrypted secrets (if any are present)
    created_saved_secret: K8sObjectMeta | None = None
    try:
        created_saved_secret = await _request_saved_secret_creation(
            user=user,
            data_service_base_url=data_service_base_url,
            dc_secrets_dict=extras.data_connector_secrets,
            deposit_config=deposit_config,
            pvc_name=pvc_name,
            owner_reference=owner_reference,
        )
    except (httpx.HTTPError, errors.ProgrammingError):
        for obj_cleanup in created_objects:
            await k8s_client.delete(obj_cleanup)
        raise
    else:
        if created_saved_secret is not None:
            created_objects.append(created_saved_secret)

    # Create all required k8s manifests
    for obj_to_create in resources_to_create:
        try:
            created_obj = await k8s_client.create(obj_to_create, refresh=True)
        except Exception:
            # delete all previously created objects because something went wrong
            for obj_cleanup in created_objects:
                await k8s_client.delete(obj_cleanup)
            raise
        else:
            created_objects.append(created_obj)

    # Start the actual job
    try:
        await k8s_client.patch(
            _convert_to_k8s_object(created_job, deposit_config.cluster_id, user.id), {"spec": {"suspend": False}}
        )
    except Exception:
        # delete all created objects if we cannot patch the job to start
        for obj_cleanup in created_objects:
            await k8s_client.delete(obj_cleanup)
        raise


def _get_deposit_job_status(job: V1Job) -> models.DepositStatus:
    if not isinstance(job.status, V1JobStatus):
        raise errors.ProgrammingError(
            message="Cannot get the status of a deposit job if the status property is fully missing."
        )
    conditions = job.status.conditions or []
    if (job.status.active or 0) > 0:
        return models.DepositStatus.in_progress
    elif any(c.type == "Complete" and c.status == "True" for c in conditions):
        return models.DepositStatus.upload_complete
    elif any(c.type == "Failed" and c.status == "True" for c in conditions):
        return models.DepositStatus.failed
    else:
        return models.DepositStatus.in_progress


async def update_deposit_status(
    user: base_models.AuthenticatedAPIUser,
    job: models.DepositJob | ULID,
    dc_repo: DataConnectorRepository,
    job_client: DepositUploadJobClient,
    namespace: str,
) -> models.DepositJob:
    """Gets the deposit, the corresponding job and updates the status in the DB."""
    if isinstance(job, ULID):
        deposit_job = await dc_repo.get_deposit(user, job)
    else:
        deposit_job = job
    dep_k8s_job = await job_client.get(deposit_job.to_meta(user_id=user.id, namespace=namespace))
    if dep_k8s_job is None or dep_k8s_job.status is None:
        return deposit_job
    latest_status = _get_deposit_job_status(dep_k8s_job)
    if latest_status != deposit_job.deposit.status:
        deposit_job = await dc_repo.update_deposit(
            user,
            deposit_job.deposit.id,
            models.DepositPatch(status=latest_status),
            etag=deposit_job.etag,
        )
    return deposit_job


async def update_deposits_statuses(
    user: base_models.AuthenticatedAPIUser,
    deposit_jobs: list[models.DepositJob],
    dc_repo: DataConnectorRepository,
    job_client: DepositUploadJobClient,
    namespace: str,
) -> list[models.DepositJob]:
    """Gets the deposits, the corresponding jobs and updates the status in the DB."""
    output = []
    for deposit_job in deposit_jobs:
        dj = await update_deposit_status(
            user=user, job=deposit_job, dc_repo=dc_repo, job_client=job_client, namespace=namespace
        )
        output.append(dj)
    return output


def validate_deposit_status_change(current: models.DepositStatus, new: models.DepositStatus) -> None:
    """Validate deposit status changes for the API."""
    match current, new:
        case models.DepositStatus.upload_complete, models.DepositStatus.complete:
            pass
        case _x, _y:
            raise errors.ValidationError(
                message="The only allowed status change is from 'upload_complete' to 'complete'."
            )
