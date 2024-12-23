"""A selection of core functions for AmaltheaSessions."""

import base64
import os
from collections.abc import AsyncIterator
from json import dumps
from pathlib import PurePosixPath
from typing import Any, cast
from urllib.parse import urljoin, urlparse

import httpx
from kubernetes.client import V1ObjectMeta, V1Secret
from sanic import Request, json
from sanic.response import JSONResponse
from yaml import safe_dump

from renku_data_services.base_models.core import AnonymousAPIUser, AuthenticatedAPIUser
from renku_data_services.crc.db import ResourcePoolRepository
from renku_data_services.data_connectors.models import DataConnectorSecret, DataConnectorWithSecrets
from renku_data_services.errors import errors
from renku_data_services.notebooks import apispec
from renku_data_services.notebooks.api.amalthea_patches import git_proxy, init_containers
from renku_data_services.notebooks.api.classes.repository import GitProvider, Repository
from renku_data_services.notebooks.api.schemas.cloud_storage import RCloneStorage
from renku_data_services.notebooks.config import NotebooksConfig
from renku_data_services.notebooks.crs import (
    AmaltheaSessionV1Alpha1,
    DataSource,
    ExtraContainer,
    ExtraVolume,
    ExtraVolumeMount,
    InitContainer,
    SecretAsVolume,
    SecretAsVolumeItem,
    State,
)
from renku_data_services.notebooks.models import ExtraSecret
from renku_data_services.notebooks.utils import get_user_secret


async def get_extra_init_containers(
    nb_config: NotebooksConfig,
    user: AnonymousAPIUser | AuthenticatedAPIUser,
    repositories: list[Repository],
    git_providers: list[GitProvider],
    storage_mount: PurePosixPath,
    work_dir: PurePosixPath,
) -> tuple[list[InitContainer], list[ExtraVolume]]:
    """Get all extra init containers that should be added to an amalthea session."""
    cert_init, cert_vols = init_containers.certificates_container(nb_config)
    session_init_containers = [InitContainer.model_validate(nb_config.k8s_v2_client.sanitize(cert_init))]
    extra_volumes = [ExtraVolume.model_validate(nb_config.k8s_v2_client.sanitize(volume)) for volume in cert_vols]
    git_clone = await init_containers.git_clone_container_v2(
        user=user,
        config=nb_config,
        repositories=repositories,
        git_providers=git_providers,
        workspace_mount_path=storage_mount,
        work_dir=work_dir,
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
        conts.append(ExtraContainer.model_validate(nb_config.k8s_v2_client.sanitize(git_proxy_container)))
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


async def get_data_sources(
    nb_config: NotebooksConfig,
    user: AnonymousAPIUser | AuthenticatedAPIUser,
    server_name: str,
    data_connectors_stream: AsyncIterator[DataConnectorWithSecrets],
    work_dir: PurePosixPath,
    storage_mount: PurePosixPath,
    cloud_storage_overrides: list[apispec.SessionCloudStoragePost],
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
            config=nb_config,
            name=dc.data_connector.name,
            secrets={str(secret.secret_id): secret.name for secret in dc.secrets},
            storage_class=nb_config.cloud_storage.storage_class,
        )
        if len(dc.secrets) > 0:
            dcs_secrets[str(dc.data_connector.id)] = dc.secrets
    if isinstance(user, AuthenticatedAPIUser) and len(dcs_secrets) > 0:
        user_secret_key = await get_user_secret(nb_config.data_service_url, user)
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
            csr.target_path = (storage_mount / csr.target_path).as_posix()
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


async def patch_session(
    body: apispec.SessionPatchRequest,
    session_id: str,
    nb_config: NotebooksConfig,
    user: AnonymousAPIUser | AuthenticatedAPIUser,
    rp_repo: ResourcePoolRepository,
) -> JSONResponse:
    """Patch an Amalthea session."""
    session = await nb_config.k8s_v2_client.get_server(session_id, user.id)
    if session is None:
        raise errors.MissingResourceError(message=f"The sesison with ID {session_id} does not exist", quiet=True)
    # TODO: Some patching should only be done when the session is in some states to avoid inadvertent restarts
    patches: dict[str, Any] = {}
    if body.resource_class_id is not None:
        rcs = await rp_repo.get_classes(user, id=body.resource_class_id)
        if len(rcs) == 0:
            raise errors.MissingResourceError(
                message=f"The resource class you requested with ID {body.resource_class_id} does not exist",
                quiet=True,
            )
        rc = rcs[0]
        patches |= dict(
            spec=dict(
                session=dict(resources=dict(requests=dict(cpu=f"{round(rc.cpu * 1000)}m", memory=f"{rc.memory}Gi")))
            )
        )
        # TODO: Add a config to specifiy the gpu kind, there is also GpuKind enum in reosurce_pools
        patches["spec"]["session"]["resources"]["requests"]["nvidia.com/gpu"] = rc.gpu
        # NOTE: K8s fails if the gpus limit is not equal to the requests because it cannot be overcommited
        patches["spec"]["session"]["resources"]["limits"] = {"nvidia.com/gpu": rc.gpu}
    if (
        body.state is not None
        and body.state.value.lower() == State.Hibernated.value.lower()
        and body.state.value.lower() != session.status.state.value.lower()
    ):
        if "spec" not in patches:
            patches["spec"] = {}
        patches["spec"]["hibernated"] = True
    elif (
        body.state is not None
        and body.state.value.lower() == State.Running.value.lower()
        and session.status.state.value.lower() != body.state.value.lower()
    ):
        if "spec" not in patches:
            patches["spec"] = {}
        patches["spec"]["hibernated"] = False

    if len(patches) > 0:
        new_session = await nb_config.k8s_v2_client.patch_server(session_id, user.id, patches)
    else:
        new_session = session

    return json(new_session.as_apispec().model_dump(exclude_none=True, mode="json"))
