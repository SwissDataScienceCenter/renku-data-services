"""A selection of core functions for AmaltheaSessions."""

from __future__ import annotations

import base64
import json
import os
import random
import string
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Protocol, TypeVar, cast
from urllib.parse import urljoin, urlparse

import httpx
from kubernetes.client import V1ObjectMeta, V1Secret
from sanic import Request
from toml import dumps
from ulid import ULID
from yaml import safe_dump

from renku_data_services.app_config import logging
from renku_data_services.base_models import RESET, AnonymousAPIUser, APIUser, AuthenticatedAPIUser, ResetType
from renku_data_services.base_models.metrics import MetricsService
from renku_data_services.crc.db import ClusterRepository, ResourcePoolRepository
from renku_data_services.crc.models import (
    ClusterSettings,
    GpuKind,
    RemoteConfigurationFirecrest,
    ResourceClass,
    ResourcePool,
    SessionProtocol,
)
from renku_data_services.data_connectors.db import (
    DataConnectorSecretRepository,
)
from renku_data_services.data_connectors.models import DataConnectorSecret, DataConnectorWithSecrets
from renku_data_services.errors import ValidationError, errors
from renku_data_services.k8s.models import ClusterConnection, K8sSecret, sanitizer
from renku_data_services.notebooks import apispec, core
from renku_data_services.notebooks.api.amalthea_patches import git_proxy, init_containers
from renku_data_services.notebooks.api.amalthea_patches.init_containers import user_secrets_extras
from renku_data_services.notebooks.api.classes.image import Image
from renku_data_services.notebooks.api.classes.repository import GitProvider, Repository
from renku_data_services.notebooks.api.schemas.cloud_storage import RCloneStorage
from renku_data_services.notebooks.config import GitProviderHelperProto, NotebooksConfig
from renku_data_services.notebooks.crs import (
    AmaltheaSessionSpec,
    AmaltheaSessionV1Alpha1,
    AmaltheaSessionV1Alpha1MetadataPatch,
    AmaltheaSessionV1Alpha1Patch,
    AmaltheaSessionV1Alpha1SpecPatch,
    AmaltheaSessionV1Alpha1SpecSessionPatch,
    Authentication,
    AuthenticationType,
    Culling,
    CullingPatch,
    DataSource,
    ExtraContainer,
    ExtraVolume,
    ExtraVolumeMount,
    ImagePullPolicy,
    ImagePullSecret,
    Ingress,
    InitContainer,
    Limits,
    LimitsStr,
    Metadata,
    ReconcileStrategy,
    Requests,
    RequestsStr,
    Resources,
    ResourcesPatch,
    SecretAsVolume,
    SecretAsVolumeItem,
    Session,
    SessionEnvItem,
    SessionLocation,
    ShmSizeStr,
    SizeStr,
    State,
    Storage,
    TlsSecret,
)
from renku_data_services.notebooks.data_sources import DataSourceRepository
from renku_data_services.notebooks.image_check import ImageCheckRepository
from renku_data_services.notebooks.models import (
    ExtraSecret,
    SessionDataConnectorOverride,
    SessionEnvVar,
    SessionExtraResources,
    SessionLaunchRequest,
)
from renku_data_services.notebooks.util.kubernetes_ import (
    renku_2_make_server_name,
)
from renku_data_services.notebooks.utils import (
    node_affinity_from_resource_class,
    node_affinity_patch_from_resource_class,
    tolerations_from_resource_class,
)
from renku_data_services.project.db import ProjectRepository, ProjectSessionSecretRepository
from renku_data_services.project.models import Project, SessionSecret
from renku_data_services.session.db import SessionRepository
from renku_data_services.session.models import SessionLauncher
from renku_data_services.users.db import UserRepo
from renku_data_services.utils.cryptography import get_encryption_key

logger = logging.getLogger(__name__)


async def get_extra_init_containers(
    nb_config: NotebooksConfig,
    user: AnonymousAPIUser | AuthenticatedAPIUser,
    repositories: list[Repository],
    git_providers: list[GitProvider],
    storage_mount: PurePosixPath,
    work_dir: PurePosixPath,
    uid: int = 1000,
    gid: int = 1000,
) -> SessionExtraResources:
    """Get all extra init containers that should be added to an amalthea session."""
    # TODO: The above statement is not correct: the init container for user secrets is not included here
    cert_init, cert_vols = init_containers.certificates_container(nb_config)
    session_init_containers = [InitContainer.model_validate(sanitizer(cert_init))]
    extra_volumes = [ExtraVolume.model_validate(sanitizer(volume)) for volume in cert_vols]
    git_clone = await init_containers.git_clone_container_v2(
        user=user,
        config=nb_config,
        repositories=repositories,
        git_providers=git_providers,
        workspace_mount_path=storage_mount,
        work_dir=work_dir,
        uid=uid,
        gid=gid,
    )
    if git_clone is not None:
        session_init_containers.append(InitContainer.model_validate(git_clone))
    return SessionExtraResources(
        init_containers=session_init_containers,
        volumes=extra_volumes,
    )


async def get_extra_containers(
    nb_config: NotebooksConfig,
    user: AnonymousAPIUser | AuthenticatedAPIUser,
    repositories: list[Repository],
    git_providers: list[GitProvider],
) -> SessionExtraResources:
    """Get the extra containers added to amalthea sessions."""
    conts: list[ExtraContainer] = []
    git_proxy_container = await git_proxy.main_container(
        user=user, config=nb_config, repositories=repositories, git_providers=git_providers
    )
    if git_proxy_container:
        conts.append(ExtraContainer.model_validate(sanitizer(git_proxy_container)))
    return SessionExtraResources(containers=conts)


async def get_auth_secret_authenticated(
    nb_config: NotebooksConfig,
    user: AuthenticatedAPIUser,
    server_name: str,
    base_server_url: str,
    base_server_path: str,
) -> ExtraSecret:
    """Get the extra secrets that need to be added to the session for an authenticated user."""
    secret_data = {}

    parsed_proxy_url = urlparse(urljoin(base_server_url + "/", "oauth2"))
    vol = ExtraVolume(
        name="renku-authorized-emails",
        secret=SecretAsVolume(
            secretName=server_name,
            items=[SecretAsVolumeItem(key="authorized_emails", path="authorized_emails")],
        ),
    )
    secret_data["auth"] = dumps(
        {
            "provider": "oidc",
            "client_id": nb_config.sessions.oidc.client_id,
            "oidc_issuer_url": nb_config.sessions.oidc.issuer_url,
            "session_cookie_minimal": True,
            "skip_provider_button": True,
            # NOTE: If the redirect url is not HTTPS then some or identity providers will fail.
            "redirect_url": urljoin(base_server_url + "/", "oauth2/callback"),
            "cookie_path": base_server_path,
            "proxy_prefix": parsed_proxy_url.path,
            "authenticated_emails_file": "/authorized_emails",
            "client_secret": nb_config.sessions.oidc.client_secret,
            "cookie_secret": base64.urlsafe_b64encode(os.urandom(32)).decode(),
            "insecure_oidc_allow_unverified_email": nb_config.sessions.oidc.allow_unverified_email,
        }
    )
    secret_data["authorized_emails"] = user.email
    secret = V1Secret(metadata=V1ObjectMeta(name=server_name), string_data=secret_data)
    vol_mount = ExtraVolumeMount(
        name="renku-authorized-emails",
        mountPath="/authorized_emails",
        subPath="authorized_emails",
    )
    return ExtraSecret(secret, vol, vol_mount)


def get_auth_secret_anonymous(nb_config: NotebooksConfig, server_name: str, request: Request) -> ExtraSecret:
    """Get the extra secrets that need to be added to the session for an anonymous user."""
    # NOTE: We extract the session cookie value here in order to avoid creating a cookie.
    # The gateway encrypts and signs cookies so the user ID injected in the request headers does not
    # match the value of the session cookie.
    session_id = cast(str | None, request.cookies.get(nb_config.session_id_cookie_name))
    if not session_id:
        raise errors.UnauthorizedError(
            message=f"You have to have a renku session cookie at {nb_config.session_id_cookie_name} "
            "in order to launch an anonymous session."
        )
    # NOTE: Amalthea looks for the token value first in the cookie and then in the authorization header
    secret_data = {
        "auth": safe_dump(
            {
                "authproxy": {
                    "token": session_id,
                    "cookie_key": nb_config.session_id_cookie_name,
                    "verbose": True,
                }
            }
        )
    }
    secret = V1Secret(metadata=V1ObjectMeta(name=server_name), string_data=secret_data)
    return ExtraSecret(secret)


async def __get_gitlab_image_pull_secret(
    nb_config: NotebooksConfig, user: AuthenticatedAPIUser, image_pull_secret_name: str, access_token: str
) -> ExtraSecret:
    """Create a Kubernetes secret for private GitLab registry authentication."""

    k8s_namespace = await nb_config.k8s_v2_client.namespace()

    registry_secret = {
        "auths": {
            nb_config.git.registry: {
                "Username": "oauth2",
                "Password": access_token,
                "Email": user.email,
            }
        }
    }
    registry_secret = json.dumps(registry_secret)

    secret_data = {".dockerconfigjson": registry_secret}
    secret = V1Secret(
        metadata=V1ObjectMeta(name=image_pull_secret_name, namespace=k8s_namespace),
        string_data=secret_data,
        type="kubernetes.io/dockerconfigjson",
    )

    return ExtraSecret(secret)


async def get_data_sources(
    request: Request,
    nb_config: NotebooksConfig,
    user: AnonymousAPIUser | AuthenticatedAPIUser,
    server_name: str,
    data_connectors_stream: AsyncIterator[DataConnectorWithSecrets],
    work_dir: PurePosixPath,
    data_connectors_overrides: list[SessionDataConnectorOverride],
    user_repo: UserRepo,
    data_source_repo: DataSourceRepository,
) -> SessionExtraResources:
    """Generate cloud storage related resources."""
    data_sources: list[DataSource] = []
    secrets: list[ExtraSecret] = []
    dcs: dict[str, RCloneStorage] = {}
    dcs_secrets: dict[str, list[DataConnectorSecret]] = {}
    user_secret_key: str | None = None
    async for dc in data_connectors_stream:
        configuration = await data_source_repo.handle_configuration(
            request=request, user=user, data_connector=dc.data_connector
        )
        if configuration is None:
            continue
        mount_folder = (
            dc.data_connector.storage.target_path
            if PurePosixPath(dc.data_connector.storage.target_path).is_absolute()
            else (work_dir / dc.data_connector.storage.target_path).as_posix()
        )
        dcs[str(dc.data_connector.id)] = RCloneStorage(
            source_path=dc.data_connector.storage.source_path,
            mount_folder=mount_folder,
            configuration=configuration,
            readonly=dc.data_connector.storage.readonly,
            name=dc.data_connector.name,
            secrets={str(secret.secret_id): secret.name for secret in dc.secrets},
            storage_class=nb_config.cloud_storage.storage_class,
        )
        if len(dc.secrets) > 0:
            dcs_secrets[str(dc.data_connector.id)] = dc.secrets
    if isinstance(user, AuthenticatedAPIUser) and len(dcs_secrets) > 0:
        secret_key = await user_repo.get_or_create_user_secret_key(user)
        user_secret_key = get_encryption_key(secret_key.encode(), user.id.encode()).decode("utf-8")
    # NOTE: Check the cloud storage overrides from the request body and if any match
    # then overwrite the projects cloud storages
    # NOTE: Cloud storages in the session launch request body that are not from the DB will cause a 404 error
    # TODO: Is this correct? -> NOTE: Overriding the configuration when a saved secret is there will cause a 422 error
    for dco in data_connectors_overrides:
        dc_id = str(dco.data_connector_id)
        if dc_id not in dcs:
            raise errors.MissingResourceError(
                message=f"You have requested a data connector with ID {dc_id} which does not exist "
                "or you don't have access to."
            )
        # NOTE: if 'skip' is true, we do not mount that data connector
        if dco.skip:
            del dcs[dc_id]
            continue
        if dco.target_path is not None and not PurePosixPath(dco.target_path).is_absolute():
            dco.target_path = (work_dir / dco.target_path).as_posix()
        dcs[dc_id] = dcs[dc_id].with_override(dco)

    # Handle potential duplicate target_path
    dcs = _deduplicate_target_paths(dcs)

    for cs_id, cs in dcs.items():
        secret_name = f"{server_name}-ds-{cs_id.lower()}"
        secret_key_needed = len(dcs_secrets.get(cs_id, [])) > 0
        if secret_key_needed and user_secret_key is None:
            raise errors.ProgrammingError(
                message=f"You have saved storage secrets for data connector {cs_id} "
                f"associated with your user ID {user.id} but no key to decrypt them, "
                "therefore we cannot mount the requested data connector. "
                "Please report this to the renku administrators."
            )
        secret = ExtraSecret(
            cs.secret(
                secret_name,
                await nb_config.k8s_v2_client.namespace(),
                user_secret_key=user_secret_key if secret_key_needed else None,
            )
        )
        secrets.append(secret)
        data_sources.append(
            DataSource(
                mountPath=cs.mount_folder,
                secretRef=secret.ref(),
                accessMode="ReadOnlyMany" if cs.readonly else "ReadWriteOnce",
            )
        )
    return SessionExtraResources(
        data_sources=data_sources,
        secrets=secrets,
        data_connector_secrets=dcs_secrets,
    )


async def patch_data_sources(
    request: Request,
    user: AnonymousAPIUser | AuthenticatedAPIUser,
    session: AmaltheaSessionV1Alpha1,
    cluster: ClusterConnection,
    nb_config: NotebooksConfig,
    data_connectors_stream: AsyncIterator[DataConnectorWithSecrets],
    data_source_repo: DataSourceRepository,
) -> SessionExtraResources:
    """Handle updating data sources definitions when resuming a session.

    This touches data connectors which use OAuth2 tokens for access.
    Other data connectors are left untouched.
    """
    secrets: list[ExtraSecret] = []
    server_name = session.metadata.name
    secret_prefix = f"{server_name}-ds-"
    dss = session.spec.dataSources or []
    mounted_dcs: list[tuple[ULID, str]] = []
    for ds in dss:
        if ds.secretRef is not None:
            name = ds.secretRef.name
            if name.startswith(secret_prefix):
                ulid = name[len(secret_prefix) :]
                try:
                    mounted_dcs.append((ULID.from_str(ulid.upper()), name))
                except ValueError:
                    logger.warning(f"Could not parse {ulid.upper()} as a ULID.")
    async for dc in data_connectors_stream:
        if not data_source_repo.is_patching_enabled(dc.data_connector):
            continue
        dc_id = dc.data_connector.id
        mounted_dc = next(filter(lambda tup: tup[0] == dc_id, mounted_dcs), None)
        if mounted_dc is None:
            continue
        _, secret_name = mounted_dc
        logger.debug(f"Patching DC secret {secret_name} for data connector {str(dc_id)}.")
        k8s_secret = await nb_config.k8s_v2_client.get_secret(
            K8sSecret.from_v1_secret(V1Secret(metadata=V1ObjectMeta(name=secret_name)), cluster)
        )
        if k8s_secret is None:
            logger.warning(f"Could not read secret {secret_name} for patching, skipping!")
            continue
        v1_secret = k8s_secret.to_v1_secret()
        secret_data: dict[str, str] = v1_secret.data
        config_data_raw = secret_data.get("configData")
        if not config_data_raw:
            logger.warning(f"Field 'configData' not found for data connector {str(dc_id)}, skipping!")
            continue
        existing_config_data: str = ""
        try:
            existing_config_data = base64.b64decode(config_data_raw).decode("utf-8")
        except Exception as err:
            logger.warning(f"Error decoding 'configData' for data connector {str(dc_id)}, skipping! {err}")
            continue
        new_config_data = await data_source_repo.handle_patching_configuration(
            request=request, user=user, data_connector=dc.data_connector, config_data=existing_config_data
        )
        if not new_config_data:
            continue
        # We re-create the secret for the data connector, with the updated configuration.
        metadata = v1_secret.metadata
        new_secret = V1Secret(
            api_version="v1",
            kind="Secret",
            metadata=V1ObjectMeta(
                name=metadata.name,
                namespace=metadata.namespace,
            ),
            data=secret_data,
        )
        new_secret.data["configData"] = base64.b64encode(new_config_data.encode("utf-8")).decode("utf-8")
        secrets.append(ExtraSecret(new_secret))

    return SessionExtraResources(secrets=secrets)


async def request_dc_secret_creation(
    user: AuthenticatedAPIUser | AnonymousAPIUser,
    nb_config: NotebooksConfig,
    manifest: AmaltheaSessionV1Alpha1,
    dc_secrets: dict[str, list[DataConnectorSecret]],
) -> None:
    """Request the specified data connector secrets to be created by the secret service."""
    if isinstance(user, AnonymousAPIUser):
        return
    owner_reference = {
        "apiVersion": manifest.apiVersion,
        "kind": manifest.kind,
        "name": manifest.metadata.name,
        "uid": manifest.metadata.uid,
    }
    secrets_url = nb_config.user_secrets.secrets_storage_service_url + "/api/secrets/kubernetes"
    headers = {"Authorization": f"bearer {user.access_token}"}

    cluster_id = None
    namespace = await nb_config.k8s_v2_client.namespace()
    if (cluster := await nb_config.k8s_v2_client.cluster_by_class_id(manifest.resource_class_id(), user)) is not None:
        cluster_id = cluster.id
        namespace = cluster.namespace

    for s_id, secrets in dc_secrets.items():
        if len(secrets) == 0:
            continue
        request_data = {
            "name": f"{manifest.metadata.name}-ds-{s_id.lower()}-secrets",
            "namespace": namespace,
            "secret_ids": [str(secret.secret_id) for secret in secrets],
            "owner_references": [owner_reference],
            "key_mapping": {str(secret.secret_id): secret.name for secret in secrets},
            "cluster_id": str(cluster_id),
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


def get_launcher_env_variables(launcher: SessionLauncher, launch_request: SessionLaunchRequest) -> list[SessionEnvItem]:
    """Get the environment variables from the launcher, with overrides from the request."""
    output: list[SessionEnvItem] = []
    env_overrides = {i.name: i.value for i in launch_request.env_variable_overrides or []}
    for env in launcher.env_variables or []:
        if env.name in env_overrides:
            output.append(SessionEnvItem(name=env.name, value=env_overrides[env.name]))
        else:
            output.append(SessionEnvItem(name=env.name, value=env.value))
    return output


def verify_launcher_env_variable_overrides(launcher: SessionLauncher, launch_request: SessionLaunchRequest) -> None:
    """Raise an error if there are env variables that are not defined in the launcher."""
    env_overrides = {i.name: i.value for i in launch_request.env_variable_overrides or []}
    known_env_names = {i.name for i in launcher.env_variables or []}
    unknown_env_names = set(env_overrides.keys()) - known_env_names
    if unknown_env_names:
        message = f"""The following environment variables are not defined in the session launcher: {unknown_env_names}.
            Please remove them from the launch request or add them to the session launcher."""
        raise errors.ValidationError(message=message)


async def request_session_secret_creation(
    user: AuthenticatedAPIUser | AnonymousAPIUser,
    nb_config: NotebooksConfig,
    manifest: AmaltheaSessionV1Alpha1,
    session_secrets: list[SessionSecret],
) -> None:
    """Request the specified user session secrets to be created by the secret service."""
    if isinstance(user, AnonymousAPIUser):
        return
    if not session_secrets:
        return
    owner_reference = {
        "apiVersion": manifest.apiVersion,
        "kind": manifest.kind,
        "name": manifest.metadata.name,
        "uid": manifest.metadata.uid,
    }
    key_mapping: dict[str, list[str]] = dict()
    for s in session_secrets:
        secret_id = str(s.secret_id)
        if secret_id not in key_mapping:
            key_mapping[secret_id] = list()
        key_mapping[secret_id].append(s.secret_slot.filename)

    cluster_id = None
    namespace = await nb_config.k8s_v2_client.namespace()
    if (cluster := await nb_config.k8s_v2_client.cluster_by_class_id(manifest.resource_class_id(), user)) is not None:
        cluster_id = cluster.id
        namespace = cluster.namespace

    request_data = {
        "name": f"{manifest.metadata.name}-secrets",
        "namespace": namespace,
        "secret_ids": [str(s.secret_id) for s in session_secrets],
        "owner_references": [owner_reference],
        "key_mapping": key_mapping,
        "cluster_id": str(cluster_id),
    }
    secrets_url = nb_config.user_secrets.secrets_storage_service_url + "/api/secrets/kubernetes"
    headers = {"Authorization": f"bearer {user.access_token}"}
    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.post(secrets_url, headers=headers, json=request_data)
        if res.status_code >= 300 or res.status_code < 200:
            raise errors.ProgrammingError(
                message="The session secrets could not be successfully created, "
                f"the status code was {res.status_code}."
                "Please contact a Renku administrator.",
                detail=res.text,
            )


def resources_patch_from_resource_class(resource_class: ResourceClass) -> ResourcesPatch:
    """Convert the resource class to a k8s resources spec."""
    gpu_name = GpuKind.NVIDIA.value + "/gpu"
    resources = resources_from_resource_class(resource_class)
    requests: Mapping[str, Requests | RequestsStr | ResetType] | ResetType | None = None
    limits: Mapping[str, Limits | LimitsStr | ResetType] | ResetType | None = None
    defaul_requests = {"memory": RESET, "cpu": RESET, gpu_name: RESET}
    default_limits = {"memory": RESET, "cpu": RESET, gpu_name: RESET}
    if resources.requests is not None:
        requests = RESET if len(resources.requests.keys()) == 0 else {**defaul_requests, **resources.requests}
    if resources.limits is not None:
        limits = RESET if len(resources.limits.keys()) == 0 else {**default_limits, **resources.limits}
    return ResourcesPatch(requests=requests, limits=limits)


def resources_from_resource_class(resource_class: ResourceClass) -> Resources:
    """Convert the resource class to a k8s resources spec."""
    requests: dict[str, Requests | RequestsStr] = {
        "cpu": RequestsStr(str(round(resource_class.cpu * 1000)) + "m"),
        "memory": RequestsStr(f"{resource_class.memory}Gi"),
    }
    limits: dict[str, Limits | LimitsStr] = {"memory": LimitsStr(f"{resource_class.memory}Gi")}
    if resource_class.gpu > 0:
        gpu_name = GpuKind.NVIDIA.value + "/gpu"
        requests[gpu_name] = Requests(resource_class.gpu)
        # NOTE: GPUs have to be set in limits too since GPUs cannot be overcommited, if
        # not on some clusters this will cause the session to fully fail to start.
        limits[gpu_name] = Limits(resource_class.gpu)
    return Resources(requests=requests, limits=limits if len(limits) > 0 else None)


def repositories_from_project(project: Project, git_providers: list[GitProvider]) -> list[Repository]:
    """Get the list of git repositories from a project."""
    repositories: list[Repository] = []
    for repo in project.repositories:
        found_provider_id: str | None = None
        for provider in git_providers:
            if urlparse(provider.url).netloc == urlparse(repo).netloc:
                found_provider_id = provider.id
                break
        repositories.append(Repository(url=repo, provider=found_provider_id))
    return repositories


async def repositories_from_session(
    user: AnonymousAPIUser | AuthenticatedAPIUser,
    session: AmaltheaSessionV1Alpha1,
    project_repo: ProjectRepository,
    git_providers: list[GitProvider],
) -> list[Repository]:
    """Get the list of git repositories from a session."""
    try:
        project = await project_repo.get_project(user, session.project_id)
    except errors.MissingResourceError:
        return []
    return repositories_from_project(project, git_providers)


def get_culling(
    user: AuthenticatedAPIUser | AnonymousAPIUser, resource_pool: ResourcePool, nb_config: NotebooksConfig
) -> Culling:
    """Create the culling specification for an AmaltheaSession."""
    hibernation_threshold: timedelta | None = None
    # NOTE: A value of zero on the resource_pool hibernation threshold
    # is interpreted by Amalthea as "never automatically delete after hibernation"
    match (user.is_anonymous, resource_pool.hibernation_threshold):
        case True, _:
            # NOTE: Anonymous sessions should not be hibernated at all, but there is no such option in Amalthea
            # So in this case we set a very low hibernation threshold so the session is deleted quickly after
            # it is hibernated.
            hibernation_threshold = timedelta(seconds=1)
        case False, int():
            hibernation_threshold = timedelta(seconds=resource_pool.hibernation_threshold)
        case False, None:
            hibernation_threshold = timedelta(seconds=nb_config.sessions.culling.registered.hibernated_seconds)

    idle_duration: timedelta | None = None
    # NOTE: A value of zero on the resource_pool idle threshold
    # is interpreted by Amalthea as "never automatically hibernate for idleness"
    match (user.is_anonymous, resource_pool.idle_threshold):
        case True, None:
            idle_duration = timedelta(seconds=nb_config.sessions.culling.anonymous.idle_seconds)
        case _, int():
            idle_duration = timedelta(seconds=resource_pool.idle_threshold)
        case False, None:
            idle_duration = timedelta(seconds=nb_config.sessions.culling.registered.idle_seconds)

    return Culling(
        maxAge=timedelta(seconds=nb_config.sessions.culling.registered.max_age_seconds),
        maxFailedDuration=timedelta(seconds=nb_config.sessions.culling.registered.failed_seconds),
        maxHibernatedDuration=hibernation_threshold,
        maxIdleDuration=idle_duration,
        maxStartingDuration=timedelta(seconds=nb_config.sessions.culling.registered.pending_seconds),
    )


def get_culling_patch(
    user: AuthenticatedAPIUser | AnonymousAPIUser,
    resource_pool: ResourcePool | None,
    nb_config: NotebooksConfig,
    lastInteraction: datetime | apispec.CurrentTime | None,
) -> CullingPatch:
    """Get the patch for the culling durations of a session."""
    lastInteractionDT: datetime | None = None
    match lastInteraction:
        case apispec.CurrentTime():
            lastInteractionDT = datetime.now(UTC).replace(microsecond=0)
        case datetime() as dt:
            if not dt.tzinfo:
                raise ValidationError(message=f"The timestamp has no timezone information: {dt}")
            if datetime.now(UTC) < dt:
                raise ValidationError(message=f"The timestamp is in the future: {dt}")
            lastInteractionDT = min(dt, datetime.now(UTC)).replace(microsecond=0)

    match resource_pool:
        case None:
            # only update lastInteraction
            return CullingPatch(lastInteraction=lastInteractionDT or RESET)
        case rp:
            culling = get_culling(user, rp, nb_config) if resource_pool else Culling()
            return CullingPatch(
                maxAge=culling.maxAge or RESET,
                maxFailedDuration=culling.maxFailedDuration or RESET,
                maxHibernatedDuration=culling.maxHibernatedDuration or RESET,
                maxIdleDuration=culling.maxIdleDuration or RESET,
                maxStartingDuration=culling.maxStartingDuration or RESET,
                lastInteraction=lastInteractionDT or RESET,
            )


async def __requires_image_pull_secret(nb_config: NotebooksConfig, image: str, internal_gitlab_user: APIUser) -> bool:
    """Determines if an image requires a pull secret based on its visibility and their GitLab access token."""

    parsed_image = Image.from_path(image)
    image_repo = parsed_image.repo_api()

    image_exists_publicly = await image_repo.image_exists(parsed_image)
    if image_exists_publicly:
        return False

    if parsed_image.hostname == nb_config.git.registry and internal_gitlab_user.access_token:
        image_repo = image_repo.with_oauth2_token(internal_gitlab_user.access_token)
        image_exists_privately = await image_repo.image_exists(parsed_image)
        if image_exists_privately:
            return True
    # No pull secret needed if the image is private and the user cannot access it
    return False


def __format_image_pull_secret(secret_name: str, access_token: str, registry_domain: str) -> ExtraSecret:
    registry_secret = {
        "auths": {registry_domain: {"auth": base64.b64encode(f"oauth2:{access_token}".encode()).decode()}}
    }
    registry_secret = json.dumps(registry_secret)
    registry_secret = base64.b64encode(registry_secret.encode()).decode()
    return ExtraSecret(
        V1Secret(
            data={".dockerconfigjson": registry_secret},
            metadata=V1ObjectMeta(name=secret_name),
            type="kubernetes.io/dockerconfigjson",
        )
    )


async def __get_connected_services_image_pull_secret(
    secret_name: str, image_check_repo: ImageCheckRepository, image: str, user: APIUser
) -> ExtraSecret | None:
    """Return a secret for accessing the image if one is available for the given user."""
    image_parsed = Image.from_path(image)
    image_check_result = await image_check_repo.check_image(user=user, gitlab_user=None, image=image_parsed)
    logger.debug(f"Set pull secret for {image} to connection {image_check_result.image_provider}")
    if not image_check_result.token:
        return None

    if not image_check_result.image_provider:
        return None

    return __format_image_pull_secret(
        secret_name=secret_name,
        access_token=image_check_result.token,
        registry_domain=image_check_result.image_provider.registry_url,
    )


async def get_image_pull_secret(
    image: str,
    server_name: str,
    nb_config: NotebooksConfig,
    user: APIUser,
    internal_gitlab_user: APIUser,
    image_check_repo: ImageCheckRepository,
) -> ExtraSecret | None:
    """Get an image pull secret."""

    v2_secret = await __get_connected_services_image_pull_secret(
        f"{server_name}-image-secret", image_check_repo, image, user
    )
    if v2_secret:
        return v2_secret

    if (
        nb_config.enable_internal_gitlab
        and isinstance(user, AuthenticatedAPIUser)
        and internal_gitlab_user.access_token is not None
    ):
        needs_pull_secret = await __requires_image_pull_secret(nb_config, image, internal_gitlab_user)
        if needs_pull_secret:
            v1_secret = await __get_gitlab_image_pull_secret(
                nb_config, user, f"{server_name}-image-secret-v1", internal_gitlab_user.access_token
            )
            return v1_secret

    return None


def get_remote_secret(
    user: AuthenticatedAPIUser | AnonymousAPIUser,
    config: NotebooksConfig,
    server_name: str,
    remote_provider_id: str,
    git_providers: list[GitProvider],
) -> ExtraSecret | None:
    """Returns the secret containing the configuration for the remote session controller."""
    if not user.is_authenticated or user.access_token is None or user.refresh_token is None:
        return None
    remote_provider = next(filter(lambda p: p.id == remote_provider_id, git_providers), None)
    if not remote_provider:
        return None
    renku_base_url = "https://" + config.sessions.ingress.host
    renku_base_url = renku_base_url.rstrip("/")
    renku_auth_token_uri = f"{renku_base_url}/auth/realms/{config.keycloak_realm}/protocol/openid-connect/token"
    secret_data = {
        "RSC_AUTH_KIND": "renku",
        "RSC_AUTH_TOKEN_URI": remote_provider.access_token_url,
        "RSC_AUTH_RENKU_ACCESS_TOKEN": user.access_token,
        "RSC_AUTH_RENKU_REFRESH_TOKEN": user.refresh_token,
        "RSC_AUTH_RENKU_TOKEN_URI": renku_auth_token_uri,
        "RSC_AUTH_RENKU_CLIENT_ID": config.sessions.git_proxy.renku_client_id,
        "RSC_AUTH_RENKU_CLIENT_SECRET": config.sessions.git_proxy.renku_client_secret,
    }
    secret_name = f"{server_name}-remote-secret"
    secret = V1Secret(metadata=V1ObjectMeta(name=secret_name), string_data=secret_data)
    return ExtraSecret(secret)


def get_remote_env(
    remote: RemoteConfigurationFirecrest,
) -> list[SessionEnvItem]:
    """Returns env variables used for remote sessions."""
    env = [
        SessionEnvItem(name="RSC_REMOTE_KIND", value=remote.kind.value),
        SessionEnvItem(name="RSC_FIRECREST_API_URL", value=remote.api_url),
        SessionEnvItem(name="RSC_FIRECREST_SYSTEM_NAME", value=remote.system_name),
    ]
    if remote.partition:
        env.append(SessionEnvItem(name="RSC_FIRECREST_PARTITION", value=remote.partition))
    return env


async def start_session(
    request: Request,
    launch_request: SessionLaunchRequest,
    user: AnonymousAPIUser | AuthenticatedAPIUser,
    internal_gitlab_user: APIUser,
    nb_config: NotebooksConfig,
    git_provider_helper: GitProviderHelperProto,
    cluster_repo: ClusterRepository,
    data_connector_secret_repo: DataConnectorSecretRepository,
    project_repo: ProjectRepository,
    project_session_secret_repo: ProjectSessionSecretRepository,
    rp_repo: ResourcePoolRepository,
    session_repo: SessionRepository,
    user_repo: UserRepo,
    metrics: MetricsService,
    image_check_repo: ImageCheckRepository,
    data_source_repo: DataSourceRepository,
) -> tuple[AmaltheaSessionV1Alpha1, bool]:
    """Start an Amalthea session.

    Returns a tuple where the first item is an instance of an Amalthea session
    and the second item is a boolean set to true iff a new session was created.
    """
    launcher = await session_repo.get_launcher(user=user, launcher_id=launch_request.launcher_id)
    launcher_id = launcher.id
    project = await project_repo.get_project(user=user, project_id=launcher.project_id)

    # Determine resource_class_id: the class can be overwritten at the user's request
    resource_class_id = launch_request.resource_class_id or launcher.resource_class_id

    cluster = await nb_config.k8s_v2_client.cluster_by_class_id(resource_class_id, user)

    server_name = renku_2_make_server_name(
        user=user, project_id=str(launcher.project_id), launcher_id=str(launcher_id), cluster_id=str(cluster.id)
    )
    existing_session = await nb_config.k8s_v2_client.get_session(name=server_name, safe_username=user.id)
    if existing_session is not None:
        return existing_session, False

    # Fully determine the resource pool and resource class
    if resource_class_id is None:
        resource_pool = await rp_repo.get_default_resource_pool()
        resource_class = resource_pool.get_default_resource_class()
        if not resource_class and len(resource_pool.classes) > 0:
            resource_class = resource_pool.classes[0]
        if not resource_class or not resource_class.id:
            raise errors.ProgrammingError(message="Cannot find any resource classes in the default pool.")
        resource_class_id = resource_class.id
    else:
        resource_pool = await rp_repo.get_resource_pool_from_class(user, resource_class_id)
        resource_class = resource_pool.get_resource_class(resource_class_id)
        if not resource_class or not resource_class.id:
            raise errors.MissingResourceError(message=f"The resource class with ID {resource_class_id} does not exist.")
    await nb_config.crc_validator.validate_class_storage(user, resource_class.id, launch_request.disk_storage)
    disk_storage = launch_request.disk_storage or resource_class.default_storage

    # Determine session location
    session_location = SessionLocation.remote if resource_pool.remote else SessionLocation.local
    if session_location == SessionLocation.remote and not user.is_authenticated:
        raise errors.ValidationError(message="Anonymous users cannot start remote sessions.")

    environment = launcher.environment
    image = environment.container_image
    work_dir = environment.working_directory
    if not work_dir:
        image_workdir = await core.docker_image_workdir(nb_config, environment.container_image, internal_gitlab_user)
        work_dir_fallback = PurePosixPath("/home/jovyan")
        work_dir = image_workdir or work_dir_fallback
    storage_mount_fallback = work_dir / "work"
    storage_mount = launcher.environment.mount_directory or storage_mount_fallback
    secrets_mount_directory = storage_mount / project.secrets_mount_directory
    session_secrets = await project_session_secret_repo.get_all_session_secrets_from_project(
        user=user, project_id=project.id
    )
    data_connectors_stream = data_connector_secret_repo.get_data_connectors_with_secrets(user, project.id)
    git_providers = await git_provider_helper.get_providers(user=user)
    repositories = repositories_from_project(project, git_providers)

    # User secrets
    session_extras = SessionExtraResources()
    session_extras = session_extras.concat(
        user_secrets_extras(
            user=user,
            config=nb_config,
            secrets_mount_directory=secrets_mount_directory.as_posix(),
            k8s_secret_name=f"{server_name}-secrets",
            session_secrets=session_secrets,
        )
    )

    # Data connectors
    session_extras = session_extras.concat(
        await get_data_sources(
            request=request,
            nb_config=nb_config,
            server_name=server_name,
            user=user,
            data_connectors_stream=data_connectors_stream,
            work_dir=work_dir,
            data_connectors_overrides=launch_request.data_connectors_overrides or [],
            user_repo=user_repo,
            data_source_repo=data_source_repo,
        )
    )

    # More init containers
    session_extras = session_extras.concat(
        await get_extra_init_containers(
            nb_config,
            user,
            repositories,
            git_providers,
            storage_mount,
            work_dir,
            uid=environment.uid,
            gid=environment.gid,
        )
    )

    # Extra containers
    session_extras = session_extras.concat(await get_extra_containers(nb_config, user, repositories, git_providers))

    # Cluster settings (ingress, storage class, etc)
    cluster_settings: ClusterSettings
    try:
        cluster_settings = await cluster_repo.select(cluster.id)
    except errors.MissingResourceError:
        # Fallback to global, main cluster parameters
        cluster_settings = nb_config.local_cluster_settings()

    ingress_config = SessionIngress(server_name=server_name, cluster_settings=cluster_settings)

    storage_class = cluster_settings.get_storage_class()
    service_account_name = cluster_settings.service_account_name

    ui_path = f"{ingress_config.url}/{environment.default_url.lstrip('/')}"

    # Annotations
    annotations: dict[str, str] = {
        "renku.io/project_id": str(launcher.project_id),
        "renku.io/launcher_id": str(launcher_id),
        "renku.io/resource_class_id": str(resource_class_id),
    }

    # Authentication
    if isinstance(user, AuthenticatedAPIUser):
        auth_secret = await get_auth_secret_authenticated(
            nb_config, user, server_name, ingress_config.url, ingress_config.url_path
        )
    else:
        auth_secret = get_auth_secret_anonymous(nb_config, server_name, request)
    session_extras = session_extras.concat(
        SessionExtraResources(
            secrets=[auth_secret],
            volumes=[auth_secret.volume] if auth_secret.volume else [],
        )
    )
    authn_extra_volume_mounts: list[ExtraVolumeMount] = []
    if auth_secret.volume_mount:
        authn_extra_volume_mounts.append(auth_secret.volume_mount)

    cert_vol_mounts = init_containers.certificates_volume_mounts(nb_config)
    if cert_vol_mounts:
        authn_extra_volume_mounts.extend(cert_vol_mounts)

    image_secret = await get_image_pull_secret(
        image=image,
        server_name=server_name,
        nb_config=nb_config,
        user=user,
        internal_gitlab_user=internal_gitlab_user,
        image_check_repo=image_check_repo,
    )
    if image_secret:
        session_extras = session_extras.concat(SessionExtraResources(secrets=[image_secret]))

    # Remote session configuration
    remote_secret = None
    if session_location == SessionLocation.remote:
        assert resource_pool.remote is not None
        if resource_pool.remote.provider_id is None:
            raise errors.ProgrammingError(
                message=f"The resource pool {resource_pool.id} configuration is not valid (missing field 'remote_provider_id')."  # noqa E501
            )
        remote_secret = get_remote_secret(
            user=user,
            config=nb_config,
            server_name=server_name,
            remote_provider_id=resource_pool.remote.provider_id,
            git_providers=git_providers,
        )
    if remote_secret is not None:
        session_extras = session_extras.concat(SessionExtraResources(secrets=[remote_secret]))

    # Raise an error if there are invalid environment variables in the request body
    verify_launcher_env_variable_overrides(launcher, launch_request)
    env = [
        SessionEnvItem(name="RENKU_BASE_URL_PATH", value=ingress_config.url_path),
        SessionEnvItem(name="RENKU_BASE_URL", value=ingress_config.url),
        SessionEnvItem(name="RENKU_MOUNT_DIR", value=storage_mount.as_posix()),
        SessionEnvItem(name="RENKU_SESSION", value="1"),
        SessionEnvItem(name="RENKU_SESSION_IP", value="0.0.0.0"),  # nosec B104
        SessionEnvItem(name="RENKU_SESSION_PORT", value=f"{environment.port}"),
        SessionEnvItem(name="RENKU_WORKING_DIR", value=work_dir.as_posix()),
        SessionEnvItem(name="RENKU_SECRETS_PATH", value=project.secrets_mount_directory.as_posix()),
        SessionEnvItem(name="RENKU_PROJECT_ID", value=str(project.id)),
        SessionEnvItem(name="RENKU_PROJECT_PATH", value=project.path.serialize()),
        SessionEnvItem(name="RENKU_LAUNCHER_ID", value=str(launcher.id)),
    ]
    if session_location == SessionLocation.remote:
        assert resource_pool.remote is not None
        env.extend(
            get_remote_env(
                remote=resource_pool.remote,
            )
        )
    launcher_env_variables = get_launcher_env_variables(launcher, launch_request)
    env.extend(launcher_env_variables)

    session = AmaltheaSessionV1Alpha1(
        metadata=Metadata(name=server_name, annotations=annotations),
        spec=AmaltheaSessionSpec(
            location=session_location,
            imagePullSecrets=[ImagePullSecret(name=image_secret.name, adopt=True)] if image_secret else [],
            codeRepositories=[],
            hibernated=False,
            reconcileStrategy=ReconcileStrategy.whenFailedOrHibernated,
            priorityClassName=resource_class.quota,
            session=Session(
                image=image,
                imagePullPolicy=ImagePullPolicy.Always,
                urlPath=ui_path,
                port=environment.port,
                storage=Storage(
                    className=storage_class,
                    size=SizeStr(str(disk_storage) + "G"),
                    mountPath=storage_mount.as_posix(),
                ),
                workingDir=work_dir.as_posix(),
                runAsUser=environment.uid,
                runAsGroup=environment.gid,
                resources=resources_from_resource_class(resource_class),
                extraVolumeMounts=session_extras.volume_mounts,
                command=environment.command,
                args=environment.args,
                shmSize=ShmSizeStr("1G"),
                stripURLPath=environment.strip_path_prefix,
                env=env,
                remoteSecretRef=remote_secret.ref() if remote_secret else None,
            ),
            ingress=ingress_config.get_k8s_ingress(),
            extraContainers=session_extras.containers,
            initContainers=session_extras.init_containers,
            extraVolumes=session_extras.volumes,
            culling=get_culling(user, resource_pool, nb_config),
            authentication=Authentication(
                enabled=True,
                type=AuthenticationType.oauth2proxy
                if isinstance(user, AuthenticatedAPIUser)
                else AuthenticationType.token,
                secretRef=auth_secret.key_ref("auth"),
                extraVolumeMounts=authn_extra_volume_mounts,
            ),
            dataSources=session_extras.data_sources,
            tolerations=tolerations_from_resource_class(resource_class, nb_config.sessions.tolerations_model),
            affinity=node_affinity_from_resource_class(resource_class, nb_config.sessions.affinity_model),
            serviceAccountName=service_account_name,
        ),
    )
    secrets_to_create = session_extras.secrets or []
    for s in secrets_to_create:
        logger.debug(f"Creating {len(secrets_to_create)} session secrets")
        await nb_config.k8s_v2_client.create_or_patch_secret(K8sSecret.from_v1_secret(s.secret, cluster))
    try:
        logger.debug(f"Starting session ${session.metadata.name} for user {user.id}")
        session = await nb_config.k8s_v2_client.create_session(session, user)
    except Exception as err:
        logger.debug(f"Removing {len(secrets_to_create)} secrets due to failing session start")
        for s in secrets_to_create:
            await nb_config.k8s_v2_client.delete_secret(K8sSecret.from_v1_secret(s.secret, cluster))
        raise errors.ProgrammingError(message="Could not start the amalthea session") from err
    else:
        try:
            await request_session_secret_creation(user, nb_config, session, session_secrets)
            data_connector_secrets = session_extras.data_connector_secrets or dict()
            await request_dc_secret_creation(user, nb_config, session, data_connector_secrets)
        except Exception:
            await nb_config.k8s_v2_client.delete_session(server_name, user.id)
            raise

    await metrics.user_requested_session_launch(
        user=user,
        metadata={
            "cpu": int(resource_class.cpu * 1000),
            "memory": resource_class.memory,
            "gpu": resource_class.gpu,
            "storage": disk_storage,
            "resource_class_id": resource_class.id,
            "resource_pool_id": resource_pool.id or "",
            "resource_class_name": f"{resource_pool.name}.{resource_class.name}",
            "session_id": server_name,
        },
    )
    return session, True


async def patch_session(
    request: Request,
    body: apispec.SessionPatchRequest,
    session_id: str,
    user: AnonymousAPIUser | AuthenticatedAPIUser,
    internal_gitlab_user: APIUser,
    nb_config: NotebooksConfig,
    git_provider_helper: GitProviderHelperProto,
    data_connector_secret_repo: DataConnectorSecretRepository,
    project_repo: ProjectRepository,
    project_session_secret_repo: ProjectSessionSecretRepository,
    rp_repo: ResourcePoolRepository,
    session_repo: SessionRepository,
    image_check_repo: ImageCheckRepository,
    data_source_repo: DataSourceRepository,
    metrics: MetricsService,
) -> AmaltheaSessionV1Alpha1:
    """Patch an Amalthea session."""
    session = await nb_config.k8s_v2_client.get_session(session_id, user.id)
    if session is None:
        raise errors.MissingResourceError(message=f"The session with ID {session_id} does not exist")
    cluster = await nb_config.k8s_v2_client.cluster_by_class_id(session.resource_class_id(), user)

    patch = AmaltheaSessionV1Alpha1Patch(spec=AmaltheaSessionV1Alpha1SpecPatch())
    is_getting_hibernated: bool = False

    # Hibernation
    # TODO: Some patching should only be done when the session is in some states to avoid inadvertent restarts
    # Refresh tokens for git proxy
    if (
        body.state is not None
        and body.state.value.lower() == State.Hibernated.value.lower()
        and body.state.value.lower() != session.status.state.value.lower()
    ):
        # Session is being hibernated
        patch.spec.hibernated = True
        is_getting_hibernated = True
    elif (
        body.state is not None
        and body.state.value.lower() == State.Running.value.lower()
        and session.status.state.value.lower() != body.state.value.lower()
    ):
        # Session is being resumed
        patch.spec.hibernated = False
        await metrics.user_requested_session_resume(user, metadata={"session_id": session_id})

    rp: ResourcePool | None = None
    # Resource class
    if body.resource_class_id is not None:
        new_cluster = await nb_config.k8s_v2_client.cluster_by_class_id(body.resource_class_id, user)
        if new_cluster.id != cluster.id:
            raise errors.ValidationError(
                message=(
                    f"The requested resource class {body.resource_class_id} is not in the "
                    f"same cluster {cluster.id} as the current resource class {session.resource_class_id()}."
                )
            )
        rp = await rp_repo.get_resource_pool_from_class(user, body.resource_class_id)
        rc = rp.get_resource_class(body.resource_class_id)
        if not rc:
            raise errors.MissingResourceError(
                message=f"The resource class you requested with ID {body.resource_class_id} does not exist"
            )
        if not patch.metadata:
            patch.metadata = AmaltheaSessionV1Alpha1MetadataPatch()
        # Patch the resource pool and class ID in the annotations
        patch.metadata.annotations = {"renku.io/resource_pool_id": str(rp.id)}
        patch.metadata.annotations = {"renku.io/resource_class_id": str(body.resource_class_id)}
        if not patch.spec.session:
            patch.spec.session = AmaltheaSessionV1Alpha1SpecSessionPatch()
        patch.spec.session.resources = resources_patch_from_resource_class(rc)
        # Tolerations
        tolerations = tolerations_from_resource_class(rc, nb_config.sessions.tolerations_model)
        patch.spec.tolerations = tolerations
        # Affinities
        patch.spec.affinity = node_affinity_patch_from_resource_class(rc, nb_config.sessions.affinity_model)
        # Priority class (if a quota is being used)
        if rc.quota is None:
            patch.spec.priorityClassName = RESET
        # Service account name
        if rp.cluster is not None:
            patch.spec.service_account_name = (
                rp.cluster.service_account_name if rp.cluster.service_account_name is not None else RESET
            )

    patch.spec.culling = get_culling_patch(user, rp, nb_config, body.lastInteraction)

    # If the session is being hibernated we do not need to patch anything else that is
    # not specifically called for in the request body, we can refresh things when the user resumes.
    if is_getting_hibernated:
        return await nb_config.k8s_v2_client.patch_session(session_id, user.id, patch.to_rfc7386())

    server_name = session.metadata.name
    launcher = await session_repo.get_launcher(user, session.launcher_id)
    project = await project_repo.get_project(user=user, project_id=session.project_id)
    environment = launcher.environment
    work_dir = environment.working_directory
    if not work_dir:
        image_workdir = await core.docker_image_workdir(nb_config, environment.container_image, internal_gitlab_user)
        work_dir_fallback = PurePosixPath("/home/jovyan")
        work_dir = image_workdir or work_dir_fallback
    storage_mount_fallback = work_dir / "work"
    storage_mount = launcher.environment.mount_directory or storage_mount_fallback
    secrets_mount_directory = storage_mount / project.secrets_mount_directory
    session_secrets = await project_session_secret_repo.get_all_session_secrets_from_project(
        user=user, project_id=project.id
    )
    data_connectors_stream = data_connector_secret_repo.get_data_connectors_with_secrets(user, project.id)
    git_providers = await git_provider_helper.get_providers(user=user)
    repositories = repositories_from_project(project, git_providers)

    # User secrets
    session_extras = SessionExtraResources()
    session_extras = session_extras.concat(
        user_secrets_extras(
            user=user,
            config=nb_config,
            secrets_mount_directory=secrets_mount_directory.as_posix(),
            k8s_secret_name=f"{server_name}-secrets",
            session_secrets=session_secrets,
        )
    )

    # Data connectors: skip
    # TODO: How can we patch data connectors? Should we even patch them?
    # TODO: The fact that `start_session()` accepts overrides for data connectors
    # TODO: but that we do not save these overrides (e.g. as annotations) means that
    # TODO: we cannot patch data connectors upon resume.
    # TODO: If we did, we would lose the user's provided overrides (e.g. unsaved credentials).
    session_extras = session_extras.concat(
        await patch_data_sources(
            request=request,
            user=user,
            session=session,
            cluster=cluster,
            nb_config=nb_config,
            data_connectors_stream=data_connectors_stream,
            data_source_repo=data_source_repo,
        )
    )

    # More init containers
    session_extras = session_extras.concat(
        await get_extra_init_containers(
            nb_config,
            user,
            repositories,
            git_providers,
            storage_mount,
            work_dir,
            uid=environment.uid,
            gid=environment.gid,
        )
    )

    # Extra containers
    session_extras = session_extras.concat(await get_extra_containers(nb_config, user, repositories, git_providers))

    # Patching the image pull secret
    image = session.spec.session.image
    image_pull_secret = await get_image_pull_secret(
        image=image,
        server_name=server_name,
        nb_config=nb_config,
        image_check_repo=image_check_repo,
        user=user,
        internal_gitlab_user=internal_gitlab_user,
    )
    if image_pull_secret:
        session_extras = session_extras.concat(SessionExtraResources(secrets=[image_pull_secret]))
        patch.spec.imagePullSecrets = [ImagePullSecret(name=image_pull_secret.name, adopt=image_pull_secret.adopt)]
    else:
        patch.spec.imagePullSecrets = RESET

    # Construct session patch
    patch.spec.extraContainers = _make_patch_spec_list(
        existing=session.spec.extraContainers or [], updated=session_extras.containers
    )
    patch.spec.initContainers = _make_patch_spec_list(
        existing=session.spec.initContainers or [], updated=session_extras.init_containers
    )
    patch.spec.extraVolumes = _make_patch_spec_list(
        existing=session.spec.extraVolumes or [], updated=session_extras.volumes
    )
    if not patch.spec.session:
        patch.spec.session = AmaltheaSessionV1Alpha1SpecSessionPatch()
    patch.spec.session.extraVolumeMounts = _make_patch_spec_list(
        existing=session.spec.session.extraVolumeMounts or [], updated=session_extras.volume_mounts
    )

    secrets_to_create = session_extras.secrets or []
    for s in secrets_to_create:
        await nb_config.k8s_v2_client.create_or_patch_secret(K8sSecret.from_v1_secret(s.secret, cluster))

    patch_serialized = patch.to_rfc7386()
    if len(patch_serialized) == 0:
        return session

    return await nb_config.k8s_v2_client.patch_session(session_id, user.id, patch_serialized)


def _deduplicate_target_paths(dcs: dict[str, RCloneStorage]) -> dict[str, RCloneStorage]:
    """Ensures that the target paths for all storages are unique.

    This method will attempt to de-duplicate the target_path for all items passed in,
    and raise an error if it fails to generate unique target_path.
    """
    result_dcs: dict[str, RCloneStorage] = {}
    mount_folders: dict[str, list[str]] = {}

    def _find_mount_folder(dc: RCloneStorage) -> str:
        mount_folder = dc.mount_folder
        if mount_folder not in mount_folders:
            return mount_folder
        # 1. Try with a "-1", "-2", etc. suffix
        mount_folder_try = f"{mount_folder}-{len(mount_folders[mount_folder])}"
        if mount_folder_try not in mount_folders:
            return mount_folder_try
        # 2. Try with a random suffix
        suffix = "".join([random.choice(string.ascii_lowercase + string.digits) for _ in range(4)])  # nosec B311
        mount_folder_try = f"{mount_folder}-{suffix}"
        if mount_folder_try not in mount_folders:
            return mount_folder_try
        raise errors.ValidationError(
            message=f"Could not start session because two or more data connectors ({', '.join(mount_folders[mount_folder])}) share the same mount point '{mount_folder}'"  # noqa E501
        )

    for dc_id, dc in dcs.items():
        original_mount_folder = dc.mount_folder
        new_mount_folder = _find_mount_folder(dc)
        # Keep track of the original mount folder here
        if new_mount_folder != original_mount_folder:
            logger.warning(f"Re-assigning data connector {dc_id} to mount point '{new_mount_folder}'")
            dc_ids = mount_folders.get(original_mount_folder, [])
            dc_ids.append(dc_id)
            mount_folders[original_mount_folder] = dc_ids
        # Keep track of the assigned mount folder here
        dc_ids = mount_folders.get(new_mount_folder, [])
        dc_ids.append(dc_id)
        mount_folders[new_mount_folder] = dc_ids
        result_dcs[dc_id] = dc.with_override(
            override=SessionDataConnectorOverride(
                skip=False,
                data_connector_id=ULID.from_str(dc_id),
                target_path=new_mount_folder,
                configuration=None,
                source_path=None,
                readonly=None,
            )
        )

    return result_dcs


class _NamedResource(Protocol):
    """Represents a resource with a name."""

    name: str


_T = TypeVar("_T", bound=_NamedResource)


def _make_patch_spec_list(existing: Sequence[_T], updated: Sequence[_T]) -> list[_T] | None:
    """Merges updated into existing by upserting items identified by their name.

    This method is used to construct session patches, merging session resources by name (containers, volumes, etc.).
    """
    patch_list = None
    if updated:
        patch_list = list(existing)
        upsert_list = list(updated)
        for upsert_item in upsert_list:
            # Find out if the upsert_item needs to be added or updated
            # found = next(enumerate(filter(lambda item: item.name == upsert_item.name, patch_list)), None)
            found = next(filter(lambda t: t[1].name == upsert_item.name, enumerate(patch_list)), None)
            if found is not None:
                idx, _ = found
                patch_list[idx] = upsert_item
            else:
                patch_list.append(upsert_item)
    return patch_list


def validate_session_post_request(body: apispec.SessionPostRequest) -> SessionLaunchRequest:
    """Validate a session launch request."""
    data_connectors_overrides = (
        [
            SessionDataConnectorOverride(
                skip=dc.skip,
                data_connector_id=ULID.from_str(dc.data_connector_id),
                configuration=dc.configuration,
                source_path=dc.source_path,
                target_path=dc.target_path,
                readonly=dc.readonly,
            )
            for dc in body.data_connectors_overrides
        ]
        if body.data_connectors_overrides
        else None
    )
    env_variable_overrides = (
        [SessionEnvVar(name=ev.name, value=ev.value) for ev in body.env_variable_overrides]
        if body.env_variable_overrides
        else None
    )
    return SessionLaunchRequest(
        launcher_id=ULID.from_str(body.launcher_id),
        disk_storage=body.disk_storage,
        resource_class_id=body.resource_class_id,
        data_connectors_overrides=data_connectors_overrides,
        env_variable_overrides=env_variable_overrides,
    )


@dataclass(kw_only=True, frozen=True, eq=True)
class SessionIngress:
    """Helper for generating ingress and related information for a session."""

    server_name: str
    cluster_settings: ClusterSettings

    def get_k8s_ingress(self) -> Ingress:
        """Get the amalthea session ingress from the cluster settings."""
        host = self.cluster_settings.session_host
        base_server_path = f"{self.cluster_settings.session_path}/{self.server_name}"
        ingress_class_name = self.cluster_settings.session_ingress_class_name
        ingress_annotations = self.cluster_settings.session_ingress_annotations

        if ingress_class_name is None:
            ingress_class_name = ingress_annotations.get("kubernetes.io/ingress.class")

        tls_secret = (
            None
            if self.cluster_settings.session_tls_secret_name is None
            or len(self.cluster_settings.session_tls_secret_name) == 0
            or self.cluster_settings.session_protocol == SessionProtocol.HTTP
            else TlsSecret(adopt=False, name=self.cluster_settings.session_tls_secret_name)
        )

        return Ingress(
            annotations=ingress_annotations,
            host=host,
            ingressClassName=ingress_class_name,
            pathPrefix=base_server_path,
            tlsSecret=tls_secret,
            useDefaultClusterTLSCert=self.cluster_settings.session_ingress_use_default_cluster_tls_cert,
        )

    @property
    def url_path(self) -> str:
        """The path portion of the url where the session can be accessed, usually the path prefix of the ingress."""
        return f"{self.cluster_settings.session_path.rstrip('/')}/{self.server_name}"

    @property
    def url(self) -> str:
        """The full url where the session can be accessed in the browser."""
        if self.cluster_settings.session_port in [80, 443]:
            # No need to specify the port in these cases. If we specify the port on https or http
            # when it is the usual port then the URL callbacks for authentication do not work.
            # I.e. if the callback is registered as https://some.host/link it will not work when a redirect
            # like https://some.host:443/link is used.
            base_server_url = (
                f"{self.cluster_settings.session_protocol.value}://{self.cluster_settings.session_host}{self.url_path}"
            )
        else:
            base_server_url = f"{self.cluster_settings.session_protocol.value}://{self.cluster_settings.session_host}:{self.cluster_settings.session_port}{self.url_path}"
        return base_server_url
