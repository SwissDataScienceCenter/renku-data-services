"""A selection of core functions for AmaltheaSessions."""

import base64
import json
import os
import random
import string
from collections.abc import AsyncIterator, Sequence
from datetime import timedelta
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
from renku_data_services.base_models import AnonymousAPIUser, APIUser, AuthenticatedAPIUser
from renku_data_services.base_models.metrics import MetricsService
from renku_data_services.connected_services.db import ConnectedServicesRepository
from renku_data_services.crc.db import ClusterRepository, ResourcePoolRepository
from renku_data_services.crc.models import GpuKind, ResourceClass, ResourcePool
from renku_data_services.data_connectors.db import (
    DataConnectorSecretRepository,
)
from renku_data_services.data_connectors.models import DataConnectorSecret, DataConnectorWithSecrets
from renku_data_services.errors import errors
from renku_data_services.k8s.models import K8sSecret, sanitizer
from renku_data_services.notebooks import apispec, core
from renku_data_services.notebooks.api.amalthea_patches import git_proxy, init_containers
from renku_data_services.notebooks.api.amalthea_patches.init_containers import user_secrets_extras
from renku_data_services.notebooks.api.classes.image import Image
from renku_data_services.notebooks.api.classes.repository import GitProvider, Repository
from renku_data_services.notebooks.api.schemas.cloud_storage import RCloneStorage
from renku_data_services.notebooks.config import NotebooksConfig
from renku_data_services.notebooks.cr_amalthea_session import TlsSecret
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
    SecretAsVolume,
    SecretAsVolumeItem,
    Session,
    SessionEnvItem,
    SessionLocation,
    ShmSizeStr,
    SizeStr,
    State,
    Storage,
)
from renku_data_services.notebooks.models import ExtraSecret, SessionExtraResources
from renku_data_services.notebooks.util.kubernetes_ import (
    renku_2_make_server_name,
)
from renku_data_services.notebooks.utils import (
    node_affinity_from_resource_class,
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
    base_server_https_url: str,
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
            "redirect_url": urljoin(base_server_https_url + "/", "oauth2/callback"),
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


def __get_gitlab_image_pull_secret(
    nb_config: NotebooksConfig, user: AuthenticatedAPIUser, image_pull_secret_name: str, access_token: str
) -> ExtraSecret:
    """Create a Kubernetes secret for private GitLab registry authentication."""

    k8s_namespace = nb_config.k8s_client.namespace()

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
    nb_config: NotebooksConfig,
    user: AnonymousAPIUser | AuthenticatedAPIUser,
    server_name: str,
    data_connectors_stream: AsyncIterator[DataConnectorWithSecrets],
    work_dir: PurePosixPath,
    cloud_storage_overrides: list[apispec.SessionCloudStoragePost],
    user_repo: UserRepo,
) -> SessionExtraResources:
    """Generate cloud storage related resources."""
    data_sources: list[DataSource] = []
    secrets: list[ExtraSecret] = []
    dcs: dict[str, RCloneStorage] = {}
    dcs_secrets: dict[str, list[DataConnectorSecret]] = {}
    user_secret_key: str | None = None
    async for dc in data_connectors_stream:
        mount_folder = (
            dc.data_connector.storage.target_path
            if PurePosixPath(dc.data_connector.storage.target_path).is_absolute()
            else (work_dir / dc.data_connector.storage.target_path).as_posix()
        )
        dcs[str(dc.data_connector.id)] = RCloneStorage(
            source_path=dc.data_connector.storage.source_path,
            mount_folder=mount_folder,
            configuration=dc.data_connector.storage.configuration,
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
    # NOTE: Overriding the configuration when a saved secret is there will cause a 422 error
    for csr in cloud_storage_overrides:
        csr_id = csr.storage_id
        if csr_id not in dcs:
            raise errors.MissingResourceError(
                message=f"You have requested a cloud storage with ID {csr_id} which does not exist "
                "or you don't have access to."
            )
        if csr.target_path is not None and not PurePosixPath(csr.target_path).is_absolute():
            csr.target_path = (work_dir / csr.target_path).as_posix()
        dcs[csr_id] = dcs[csr_id].with_override(csr)

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
                await nb_config.k8s_client.namespace(),
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


def get_launcher_env_variables(launcher: SessionLauncher, body: apispec.SessionPostRequest) -> list[SessionEnvItem]:
    """Get the environment variables from the launcher, with overrides from the request."""
    output: list[SessionEnvItem] = []
    env_overrides = {i.name: i.value for i in body.env_variable_overrides or []}
    for env in launcher.env_variables or []:
        if env.name in env_overrides:
            output.append(SessionEnvItem(name=env.name, value=env_overrides[env.name]))
        else:
            output.append(SessionEnvItem(name=env.name, value=env.value))
    return output


def verify_launcher_env_variable_overrides(launcher: SessionLauncher, body: apispec.SessionPostRequest) -> None:
    """Raise an error if there are env variables that are not defined in the launcher."""
    env_overrides = {i.name: i.value for i in body.env_variable_overrides or []}
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
    idle_threshold_seconds = resource_pool.idle_threshold or nb_config.sessions.culling.registered.idle_seconds
    if user.is_anonymous:
        # NOTE: Anonymous sessions should not be hibernated at all, but there is no such option in Amalthea
        # So in this case we set a very low hibernation threshold so the session is deleted quickly after
        # it is hibernated.
        hibernation_threshold_seconds = 1
    else:
        hibernation_threshold_seconds = (
            resource_pool.hibernation_threshold or nb_config.sessions.culling.registered.hibernated_seconds
        )
    return Culling(
        maxAge=timedelta(seconds=nb_config.sessions.culling.registered.max_age_seconds),
        maxFailedDuration=timedelta(seconds=nb_config.sessions.culling.registered.failed_seconds),
        maxHibernatedDuration=timedelta(seconds=hibernation_threshold_seconds),
        maxIdleDuration=timedelta(seconds=idle_threshold_seconds),
        maxStartingDuration=timedelta(seconds=nb_config.sessions.culling.registered.pending_seconds),
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
        "auths": {
            registry_domain: {
                "Username": "oauth2",
                "Password": access_token,
            }
        }
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


async def __get_gitlab_image_pull_secret_v2(
    secret_name: str, connected_svcs_repo: ConnectedServicesRepository, image: str, user: APIUser
) -> ExtraSecret | None:
    """Determines if an image requires a pull secret based on its visibility and their GitLab access token."""
    # Check if image is public
    image_parsed = Image.from_path(image)
    public_repo = image_parsed.repo_api()
    image_exists_publicly = await public_repo.image_exists(image_parsed)
    if image_exists_publicly:
        return None
    # Check if image is private
    docker_client, conn_id = await connected_svcs_repo.get_docker_client(user, image_parsed)
    if not docker_client:
        return None
    image_exists_privately = await docker_client.image_exists(image_parsed)
    if not image_exists_privately:
        return None
    if not conn_id:
        return None
    if not docker_client.oauth2_token:
        return None
    return __format_image_pull_secret(
        secret_name=secret_name,
        access_token=docker_client.oauth2_token,
        registry_domain=image_parsed.hostname,
    )


async def get_image_pull_secret(
    image: str,
    server_name: str,
    nb_config: NotebooksConfig,
    user: APIUser,
    internal_gitlab_user: APIUser,
    connected_svcs_repo: ConnectedServicesRepository,
) -> tuple[ExtraSecret | None, str]:
    """Get na image pull secret if needed, currently only supports Gitlab."""
    image_secret: ExtraSecret | None = None
    image_pull_secret_name = f"{server_name}-image-secret"
    if nb_config.enable_internal_gitlab:
        # NOTE: This is the old flow where Gitlab is enabled and part of Renku
        if isinstance(user, AuthenticatedAPIUser) and internal_gitlab_user.access_token is not None:
            needs_pull_secret = await __requires_image_pull_secret(nb_config, image, internal_gitlab_user)

            if needs_pull_secret:
                image_secret = __get_gitlab_image_pull_secret(
                    nb_config, user, image_pull_secret_name, internal_gitlab_user.access_token
                )
    else:
        # NOTE: No internal Gitlab, we get the image pull secret from the connected services
        image_secret = await __get_gitlab_image_pull_secret_v2(image_pull_secret_name, connected_svcs_repo, image, user)
    return image_secret, image_pull_secret_name


def get_remote_secret(
    user: AuthenticatedAPIUser | AnonymousAPIUser,
    config: NotebooksConfig,
    server_name: str,
    git_providers: list[GitProvider],
) -> ExtraSecret | None:
    """Returns the secret containing the configuration for the remote session controller."""
    if not user.is_authenticated or user.access_token is None or user.refresh_token is None:
        return None
    # TODO: where do we configure this?
    cscs_provider = next(filter(lambda p: p.id == "cscs.ch", git_providers), None)
    if not cscs_provider:
        return None
    renku_base_url = "https://" + config.sessions.ingress.host
    renku_base_url = renku_base_url + "/" if renku_base_url.endswith("/") else renku_base_url
    renku_auth_token_uri = f"{renku_base_url}auth/realms/{config.keycloak_realm}/protocol/openid-connect/token"
    secret_data = {
        # TODO: where do we configure this?
        "FIRECREST_API_URL": "https://api.cscs.ch/hpc/firecrest/v2/",
        "FIRECREST_AUTH_TOKEN_URI": cscs_provider.access_token_url,
        "RENKU_ACCESS_TOKEN": user.access_token,
        "RENKU_REFRESH_TOKEN": user.refresh_token,
        "RENKU_AUTH_TOKEN_URI": renku_auth_token_uri,
        "RENKU_CLIENT_ID": config.sessions.git_proxy.renku_client_id,
        "RENKU_CLIENT_SECRET": config.sessions.git_proxy.renku_client_secret,
    }
    secret_name = f"{server_name}-remote-secret"
    k8s_namespace = config.k8s_client.namespace()
    secret = V1Secret(
        metadata=V1ObjectMeta(name=secret_name, namespace=k8s_namespace),
        string_data=secret_data,
        type="kubernetes.io/dockerconfigjson",
    )
    return ExtraSecret(secret)


async def start_session(
    request: Request,
    body: apispec.SessionPostRequest,
    user: AnonymousAPIUser | AuthenticatedAPIUser,
    internal_gitlab_user: APIUser,
    nb_config: NotebooksConfig,
    cluster_repo: ClusterRepository,
    data_connector_secret_repo: DataConnectorSecretRepository,
    project_repo: ProjectRepository,
    project_session_secret_repo: ProjectSessionSecretRepository,
    rp_repo: ResourcePoolRepository,
    session_repo: SessionRepository,
    user_repo: UserRepo,
    metrics: MetricsService,
    connected_svcs_repo: ConnectedServicesRepository,
) -> tuple[AmaltheaSessionV1Alpha1, bool]:
    """Start an Amalthea session.

    Returns a tuple where the first item is an instance of an Amalthea session
    and the second item is a boolean set to true iff a new session was created.
    """
    launcher = await session_repo.get_launcher(user, ULID.from_str(body.launcher_id))
    project = await project_repo.get_project(user=user, project_id=launcher.project_id)

    # Determine resource_class_id: the class can be overwritten at the user's request
    resource_class_id = body.resource_class_id or launcher.resource_class_id

    cluster = await nb_config.k8s_v2_client.cluster_by_class_id(resource_class_id, user)

    server_name = renku_2_make_server_name(
        user=user, project_id=str(launcher.project_id), launcher_id=body.launcher_id, cluster_id=str(cluster.id)
    )
    existing_session = await nb_config.k8s_v2_client.get_session(server_name, user.id)
    if existing_session is not None and existing_session.spec is not None:
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
    await nb_config.crc_validator.validate_class_storage(user, resource_class.id, body.disk_storage)

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
    git_providers = await nb_config.git_provider_helper.get_providers(user=user)
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
            nb_config=nb_config,
            server_name=server_name,
            user=user,
            data_connectors_stream=data_connectors_stream,
            work_dir=work_dir,
            cloud_storage_overrides=body.cloudstorage or [],
            user_repo=user_repo,
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

    # Ingress
    try:
        cluster_settings = await cluster_repo.select(cluster.id)
    except errors.MissingResourceError:
        cluster_settings = None

    if cluster_settings is not None:
        (
            base_server_path,
            base_server_url,
            base_server_https_url,
            host,
            tls_secret,
            ingress_annotations,
        ) = cluster_settings.get_ingress_parameters(server_name)
        storage_class = cluster_settings.get_storage_class()
        service_account_name = cluster_settings.service_account_name
    else:
        # Fallback to global, main cluster parameters
        host = nb_config.sessions.ingress.host
        base_server_path = nb_config.sessions.ingress.base_path(server_name)
        base_server_url = nb_config.sessions.ingress.base_url(server_name)
        base_server_https_url = nb_config.sessions.ingress.base_url(server_name, force_https=True)
        storage_class = nb_config.sessions.storage.pvs_storage_class
        service_account_name = None
        ingress_annotations = nb_config.sessions.ingress.annotations

        tls_name = nb_config.sessions.ingress.tls_secret
        tls_secret = None if tls_name is None else TlsSecret(adopt=False, name=tls_name)

    ui_path = f"{base_server_path}/{environment.default_url.lstrip('/')}"

    ingress = Ingress(
        host=host,
        ingressClassName=ingress_annotations.get("kubernetes.io/ingress.class"),
        annotations=ingress_annotations,
        tlsSecret=tls_secret,
        pathPrefix=base_server_path,
    )

    # Annotations
    annotations: dict[str, str] = {
        "renku.io/project_id": str(launcher.project_id),
        "renku.io/launcher_id": body.launcher_id,
        "renku.io/resource_class_id": str(resource_class_id),
    }

    # Authentication
    if isinstance(user, AuthenticatedAPIUser):
        auth_secret = await get_auth_secret_authenticated(
            nb_config, user, server_name, base_server_url, base_server_https_url, base_server_path
        )
    else:
        auth_secret = get_auth_secret_anonymous(nb_config, server_name, request)
    session_extras = session_extras.concat(
        SessionExtraResources(
            secrets=[auth_secret],
            volumes=[auth_secret.volume] if auth_secret.volume else [],
        )
    )

    image_secret, image_pull_secret_name = await get_image_pull_secret(
        image=image,
        server_name=server_name,
        nb_config=nb_config,
        user=user,
        internal_gitlab_user=internal_gitlab_user,
        connected_svcs_repo=connected_svcs_repo,
    )
    if image_secret:
        session_extras = session_extras.concat(SessionExtraResources(secrets=[image_secret]))

    # Remote session configuration
    remote_secret = (
        get_remote_secret(
            user=user,
            config=nb_config,
            server_name=server_name,
            git_providers=git_providers,
        )
        if session_location == SessionLocation.remote
        else None
    )

    # Raise an error if there are invalid environment variables in the request body
    verify_launcher_env_variable_overrides(launcher, body)
    env = [
        SessionEnvItem(name="RENKU_BASE_URL_PATH", value=base_server_path),
        SessionEnvItem(name="RENKU_BASE_URL", value=base_server_url),
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
    launcher_env_variables = get_launcher_env_variables(launcher, body)
    if launcher_env_variables:
        env.extend(launcher_env_variables)

    session = AmaltheaSessionV1Alpha1(
        metadata=Metadata(name=server_name, annotations=annotations),
        spec=AmaltheaSessionSpec(
            location=session_location,
            imagePullSecrets=[ImagePullSecret(name=image_pull_secret_name, adopt=True)] if image_secret else [],
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
                    size=SizeStr(str(body.disk_storage) + "G"),
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
            ingress=ingress,
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
                extraVolumeMounts=[auth_secret.volume_mount] if auth_secret.volume_mount else None,
            ),
            dataSources=session_extras.data_sources,
            tolerations=tolerations_from_resource_class(resource_class, nb_config.sessions.tolerations_model),
            affinity=node_affinity_from_resource_class(resource_class, nb_config.sessions.affinity_model),
            serviceAccountName=service_account_name,
        ),
    )
    secrets_to_create = session_extras.secrets or []
    for s in secrets_to_create:
        await nb_config.k8s_v2_client.create_secret(K8sSecret.from_v1_secret(s.secret, cluster))
    try:
        session = await nb_config.k8s_v2_client.create_session(session, user)
    except Exception as err:
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
            "storage": body.disk_storage,
            "resource_class_id": resource_class.id,
            "resource_pool_id": resource_pool.id or "",
            "resource_class_name": f"{resource_pool.name}.{resource_class.name}",
            "session_id": server_name,
        },
    )
    return session, True


async def patch_session(
    body: apispec.SessionPatchRequest,
    session_id: str,
    user: AnonymousAPIUser | AuthenticatedAPIUser,
    internal_gitlab_user: APIUser,
    nb_config: NotebooksConfig,
    project_repo: ProjectRepository,
    project_session_secret_repo: ProjectSessionSecretRepository,
    rp_repo: ResourcePoolRepository,
    session_repo: SessionRepository,
    connected_svcs_repo: ConnectedServicesRepository,
    metrics: MetricsService,
) -> AmaltheaSessionV1Alpha1:
    """Patch an Amalthea session."""
    session = await nb_config.k8s_v2_client.get_session(session_id, user.id)
    if session is None:
        raise errors.MissingResourceError(message=f"The session with ID {session_id} does not exist")
    if session.spec is None:
        raise errors.ProgrammingError(
            message=f"The session {session_id} being patched is missing the expected 'spec' field.", quiet=True
        )
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
        # TODO: reject session classes which change the cluster
        if not patch.metadata:
            patch.metadata = AmaltheaSessionV1Alpha1MetadataPatch()
        # Patch the resource class ID in the annotations
        patch.metadata.annotations = {"renku.io/resource_class_id": str(body.resource_class_id)}
        if not patch.spec.session:
            patch.spec.session = AmaltheaSessionV1Alpha1SpecSessionPatch()
        patch.spec.session.resources = resources_from_resource_class(rc)
        # Tolerations
        tolerations = tolerations_from_resource_class(rc, nb_config.sessions.tolerations_model)
        patch.spec.tolerations = tolerations
        # Affinities
        patch.spec.affinity = node_affinity_from_resource_class(rc, nb_config.sessions.affinity_model)
        # Priority class (if a quota is being used)
        patch.spec.priorityClassName = rc.quota
        patch.spec.culling = get_culling(user, rp, nb_config)
        if rp.cluster is not None:
            patch.spec.service_account_name = rp.cluster.service_account_name

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
    git_providers = await nb_config.git_provider_helper.get_providers(user=user)
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
    image_pull_secret, _ = await get_image_pull_secret(
        image=image,
        server_name=server_name,
        nb_config=nb_config,
        connected_svcs_repo=connected_svcs_repo,
        user=user,
        internal_gitlab_user=internal_gitlab_user,
    )
    if image_pull_secret:
        session_extras.concat(SessionExtraResources(secrets=[image_pull_secret]))
        patch.spec.imagePullSecrets = [ImagePullSecret(name=image_pull_secret.name, adopt=image_pull_secret.adopt)]

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
        await nb_config.k8s_v2_client.create_secret(K8sSecret.from_v1_secret(s.secret, cluster))

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
            override=apispec.SessionCloudStoragePost(storage_id=dc_id, target_path=new_mount_folder)
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
