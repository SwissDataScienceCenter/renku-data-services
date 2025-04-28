"""A selection of core functions for AmaltheaSessions."""

import base64
import json
import os
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import PurePosixPath
from typing import cast
from urllib.parse import urljoin, urlparse

import httpx
from kubernetes.client import V1ObjectMeta, V1Secret
from kubernetes.utils.duration import format_duration
from sanic import Request
from toml import dumps
from yaml import safe_dump

from renku_data_services.base_models import APIUser
from renku_data_services.base_models.core import AnonymousAPIUser, AuthenticatedAPIUser
from renku_data_services.crc.db import ResourcePoolRepository
from renku_data_services.crc.models import GpuKind, ResourceClass, ResourcePool
from renku_data_services.data_connectors.models import DataConnectorSecret, DataConnectorWithSecrets
from renku_data_services.errors import errors
from renku_data_services.notebooks import apispec
from renku_data_services.notebooks.api.amalthea_patches import git_proxy, init_containers
from renku_data_services.notebooks.api.classes.image import Image
from renku_data_services.notebooks.api.classes.k8s_client import sanitize_for_serialization
from renku_data_services.notebooks.api.classes.repository import GitProvider, Repository
from renku_data_services.notebooks.api.schemas.cloud_storage import RCloneStorage
from renku_data_services.notebooks.config import NotebooksConfig
from renku_data_services.notebooks.crs import (
    AmaltheaSessionV1Alpha1,
    AmaltheaSessionV1Alpha1Patch,
    AmaltheaSessionV1Alpha1SpecPatch,
    AmaltheaSessionV1Alpha1SpecSessionPatch,
    Culling,
    DataSource,
    ExtraContainer,
    ExtraVolume,
    ExtraVolumeMount,
    ImagePullSecret,
    InitContainer,
    Resources,
    SecretAsVolume,
    SecretAsVolumeItem,
    SessionEnvItem,
    State,
)
from renku_data_services.notebooks.models import ExtraSecret
from renku_data_services.notebooks.utils import (
    node_affinity_from_resource_class,
    tolerations_from_resource_class,
)
from renku_data_services.project.db import ProjectRepository
from renku_data_services.project.models import Project, SessionSecret
from renku_data_services.session.models import SessionLauncher
from renku_data_services.users.db import UserRepo
from renku_data_services.utils.cryptography import get_encryption_key


async def get_extra_init_containers(
    nb_config: NotebooksConfig,
    user: AnonymousAPIUser | AuthenticatedAPIUser,
    repositories: list[Repository],
    git_providers: list[GitProvider],
    storage_mount: PurePosixPath,
    work_dir: PurePosixPath,
    uid: int = 1000,
    gid: int = 1000,
) -> tuple[list[InitContainer], list[ExtraVolume]]:
    """Get all extra init containers that should be added to an amalthea session."""
    cert_init, cert_vols = init_containers.certificates_container(nb_config)
    session_init_containers = [InitContainer.model_validate(sanitize_for_serialization(cert_init))]
    extra_volumes = [ExtraVolume.model_validate(sanitize_for_serialization(volume)) for volume in cert_vols]
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
    return session_init_containers, extra_volumes


async def get_extra_containers(
    nb_config: NotebooksConfig,
    user: AnonymousAPIUser | AuthenticatedAPIUser,
    repositories: list[Repository],
    git_providers: list[GitProvider],
) -> list[ExtraContainer]:
    """Get the extra containers added to amalthea sessions."""
    conts: list[ExtraContainer] = []
    git_proxy_container = await git_proxy.main_container(
        user=user, config=nb_config, repositories=repositories, git_providers=git_providers
    )
    if git_proxy_container:
        conts.append(ExtraContainer.model_validate(sanitize_for_serialization(git_proxy_container)))
    return conts


async def get_auth_secret_authenticated(
    nb_config: NotebooksConfig, user: AuthenticatedAPIUser, server_name: str
) -> ExtraSecret:
    """Get the extra secrets that need to be added to the session for an authenticated user."""
    secret_data = {}
    base_server_url = nb_config.sessions.ingress.base_url(server_name)
    base_server_path = nb_config.sessions.ingress.base_path(server_name)
    base_server_https_url = nb_config.sessions.ingress.base_url(server_name, force_https=True)
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


async def get_auth_secret_anonymous(nb_config: NotebooksConfig, server_name: str, request: Request) -> ExtraSecret:
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
    secret_data = {}
    secret_data["auth"] = safe_dump(
        {
            "authproxy": {
                "token": session_id,
                "cookie_key": nb_config.session_id_cookie_name,
                "verbose": True,
            }
        }
    )
    secret = V1Secret(metadata=V1ObjectMeta(name=server_name), string_data=secret_data)
    return ExtraSecret(secret)


def get_gitlab_image_pull_secret(
    nb_config: NotebooksConfig, user: AuthenticatedAPIUser, image_pull_secret_name: str, access_token: str
) -> ExtraSecret:
    """Create a Kubernetes secret for private GitLab registry authentication."""

    preferred_namespace = nb_config.k8s_client.preferred_namespace

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
        metadata=V1ObjectMeta(name=image_pull_secret_name, namespace=preferred_namespace),
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
) -> tuple[list[DataSource], list[ExtraSecret], dict[str, list[DataConnectorSecret]]]:
    """Generate cloud storage related resources."""
    data_sources: list[DataSource] = []
    secrets: list[ExtraSecret] = []
    dcs: dict[str, RCloneStorage] = {}
    dcs_secrets: dict[str, list[DataConnectorSecret]] = {}
    async for dc in data_connectors_stream:
        dcs[str(dc.data_connector.id)] = RCloneStorage(
            source_path=dc.data_connector.storage.source_path,
            mount_folder=dc.data_connector.storage.target_path
            if PurePosixPath(dc.data_connector.storage.target_path).is_absolute()
            else (work_dir / dc.data_connector.storage.target_path).as_posix(),
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
                "or you dont have access to.",
                quiet=True,
            )
        if csr.target_path is not None and not PurePosixPath(csr.target_path).is_absolute():
            csr.target_path = (work_dir / csr.target_path).as_posix()
        dcs[csr_id] = dcs[csr_id].with_override(csr)
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
                nb_config.k8s_client.preferred_namespace,
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
    return data_sources, secrets, dcs_secrets


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
    for s_id, secrets in dc_secrets.items():
        if len(secrets) == 0:
            continue
        request_data = {
            "name": f"{manifest.metadata.name}-ds-{s_id.lower()}-secrets",
            "namespace": nb_config.k8s_v2_client.preferred_namespace,
            "secret_ids": [str(secret.secret_id) for secret in secrets],
            "owner_references": [owner_reference],
            "key_mapping": {str(secret.secret_id): secret.name for secret in secrets},
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
    request_data = {
        "name": f"{manifest.metadata.name}-secrets",
        "namespace": nb_config.k8s_v2_client.preferred_namespace,
        "secret_ids": [str(s.secret_id) for s in session_secrets],
        "owner_references": [owner_reference],
        "key_mapping": key_mapping,
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
    requests: dict[str, str | int] = {
        "cpu": str(round(resource_class.cpu * 1000)) + "m",
        "memory": f"{resource_class.memory}Gi",
    }
    limits: dict[str, str | int] = {"memory": f"{resource_class.memory}Gi"}
    if resource_class.gpu > 0:
        gpu_name = GpuKind.NVIDIA.value + "/gpu"
        requests[gpu_name] = resource_class.gpu
        # NOTE: GPUs have to be set in limits too since GPUs cannot be overcommited, if
        # not on some clusters this will cause the session to fully fail to start.
        limits[gpu_name] = resource_class.gpu
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


def get_culling(resource_pool: ResourcePool, nb_config: NotebooksConfig) -> Culling:
    """Create the culling specification for an AmaltheaSession."""
    idle_threshold_seconds = resource_pool.idle_threshold or nb_config.sessions.culling.registered.idle_seconds
    hibernation_threshold_seconds = (
        resource_pool.hibernation_threshold or nb_config.sessions.culling.registered.hibernated_seconds
    )
    return Culling(
        maxAge=format_duration(timedelta(seconds=nb_config.sessions.culling.registered.max_age_seconds)),
        maxFailedDuration=format_duration(timedelta(seconds=nb_config.sessions.culling.registered.failed_seconds)),
        maxHibernatedDuration=format_duration(timedelta(seconds=hibernation_threshold_seconds)),
        maxIdleDuration=format_duration(timedelta(seconds=idle_threshold_seconds)),
        maxStartingDuration=format_duration(timedelta(seconds=nb_config.sessions.culling.registered.pending_seconds)),
    )


async def requires_image_pull_secret(nb_config: NotebooksConfig, image: str, internal_gitlab_user: APIUser) -> bool:
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


async def patch_session(
    body: apispec.SessionPatchRequest,
    session_id: str,
    nb_config: NotebooksConfig,
    user: AnonymousAPIUser | AuthenticatedAPIUser,
    internal_gitlab_user: APIUser,
    rp_repo: ResourcePoolRepository,
    project_repo: ProjectRepository,
) -> AmaltheaSessionV1Alpha1:
    """Patch an Amalthea session."""
    session = await nb_config.k8s_v2_client.get_server(session_id, user.id)
    if session is None:
        raise errors.MissingResourceError(message=f"The session with ID {session_id} does not exist", quiet=True)
    if session.spec is None:
        raise errors.ProgrammingError(
            message=f"The session {session_id} being patched is missing the expected 'spec' field.", quiet=True
        )

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

    # Resource class
    if body.resource_class_id is not None:
        rp = await rp_repo.get_resource_pool_from_class(user, body.resource_class_id)
        rc = rp.get_resource_class(body.resource_class_id)
        if not rc:
            raise errors.MissingResourceError(
                message=f"The resource class you requested with ID {body.resource_class_id} does not exist",
                quiet=True,
            )
        if not patch.spec.session:
            patch.spec.session = AmaltheaSessionV1Alpha1SpecSessionPatch()
        patch.spec.session.resources = resources_from_resource_class(rc)
        # Tolerations
        tolerations = tolerations_from_resource_class(rc, nb_config.sessions.tolerations_model)
        if tolerations:
            patch.spec.tolerations = tolerations
        # Affinities
        patch.spec.affinity = node_affinity_from_resource_class(rc, nb_config.sessions.affinity_model)
        # Priority class (if a quota is being used)
        if rc.quota:
            patch.spec.priorityClassName = rc.quota
        patch.spec.culling = get_culling(rp, nb_config)

    # If the session is being hibernated we do not need to patch anything else that is
    # not specifically called for in the request body, we can refresh things when the user resumes.
    if is_getting_hibernated:
        return await nb_config.k8s_v2_client.patch_server(session_id, user.id, patch.to_rfc7386())

    # Patching the extra containers (includes the git proxy)
    git_providers = await nb_config.git_provider_helper.get_providers(user)
    repositories = await repositories_from_session(user, session, project_repo, git_providers)
    extra_containers = await get_extra_containers(
        nb_config,
        user,
        repositories,
        git_providers,
    )
    if extra_containers:
        patch.spec.extraContainers = extra_containers

    if isinstance(user, AuthenticatedAPIUser) and internal_gitlab_user.access_token is not None:
        image = session.spec.session.image
        server_name = session.metadata.name
        needs_pull_secret = await requires_image_pull_secret(nb_config, image, internal_gitlab_user)

        if needs_pull_secret:
            image_pull_secret_name = f"{server_name}-image-secret"

            # Always create a fresh secret to ensure we have the latest token
            image_secret = get_gitlab_image_pull_secret(
                nb_config, user, image_pull_secret_name, internal_gitlab_user.access_token
            )
            if image_secret:
                updated_secrets = [
                    secret
                    for secret in (session.spec.imagePullSecrets or [])
                    if not secret.name.endswith("-image-secret")
                ]
                updated_secrets.append(ImagePullSecret(name=image_pull_secret_name, adopt=True))
                patch.spec.imagePullSecrets = updated_secrets

    patch_serialized = patch.to_rfc7386()
    if len(patch_serialized) == 0:
        return session

    return await nb_config.k8s_v2_client.patch_server(session_id, user.id, patch_serialized)
