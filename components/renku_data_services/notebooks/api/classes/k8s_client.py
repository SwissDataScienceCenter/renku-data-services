"""An abstraction over the kr8s kubernetes client and the k8s-watcher."""

from __future__ import annotations

import base64
import json
from typing import Any, cast

import httpx
from box import Box
from kr8s import NotFoundError, ServerError
from kr8s.asyncio.objects import Pod, Secret, StatefulSet

from renku_data_services.app_config import logging
from renku_data_services.base_models import APIUser
from renku_data_services.crc.db import ResourcePoolRepository
from renku_data_services.errors import errors
from renku_data_services.k8s.client_interfaces import SecretClient
from renku_data_services.k8s.clients import K8sClusterClientsPool
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER, ClusterId
from renku_data_services.k8s.models import GVK, ClusterConnection, K8sObject, K8sObjectFilter, K8sObjectMeta, K8sSecret
from renku_data_services.notebooks.api.classes.auth import GitlabToken, RenkuTokens
from renku_data_services.notebooks.crs import AmaltheaSessionV1Alpha1
from renku_data_services.notebooks.util.kubernetes_ import find_env_var
from renku_data_services.notebooks.util.retries import retry_with_exponential_backoff_async


class NotebookK8sClient(SecretClient):
    """A K8s Client for Notebooks."""

    def __init__(
        self,
        client: K8sClusterClientsPool,
        secrets_client: SecretClient,
        rp_repo: ResourcePoolRepository,
        session_type: type[AmaltheaSessionV1Alpha1],
        username_label: str,
        gvk: GVK,
    ) -> None:
        self.__client = client
        self.__secrets_client = secrets_client
        self.__rp_repo = rp_repo
        self.__session_type: type[AmaltheaSessionV1Alpha1] = session_type
        self.__session_gvk = gvk
        self.__username_label = username_label

    @staticmethod
    def _get_statefulset_token_patches(sts: StatefulSet, renku_tokens: RenkuTokens) -> list[dict[str, str]]:
        """Patch the Renku and Gitlab access tokens that are used in the session statefulset."""
        containers = cast(list[Box], sts.spec.template.spec.containers)
        init_containers = cast(list[Box], sts.spec.template.spec.initContainers)

        git_proxy_container_index, git_proxy_container = next(
            ((i, c) for i, c in enumerate(containers) if c.name == "git-proxy"),
            (None, None),
        )
        git_clone_container_index, git_clone_container = next(
            ((i, c) for i, c in enumerate(init_containers) if c.name == "git-clone"),
            (None, None),
        )
        secrets_container_index, secrets_container = next(
            ((i, c) for i, c in enumerate(init_containers) if c.name == "init-user-secrets"),
            (None, None),
        )

        def _get_env(container: Box) -> list[Box]:
            return cast(list[Box], container.env)

        git_proxy_renku_access_token_env = (
            find_env_var(_get_env(git_proxy_container), "GIT_PROXY_RENKU_ACCESS_TOKEN")
            if git_proxy_container is not None
            else None
        )
        git_proxy_renku_refresh_token_env = (
            find_env_var(_get_env(git_proxy_container), "GIT_PROXY_RENKU_REFRESH_TOKEN")
            if git_proxy_container is not None
            else None
        )
        git_clone_renku_access_token_env = (
            find_env_var(_get_env(git_clone_container), "GIT_CLONE_USER__RENKU_TOKEN")
            if git_clone_container is not None
            else None
        )
        secrets_renku_access_token_env = (
            find_env_var(_get_env(secrets_container), "RENKU_ACCESS_TOKEN") if secrets_container is not None else None
        )

        patches = list()
        if git_proxy_container_index is not None and git_proxy_renku_access_token_env is not None:
            patches.append(
                {
                    "op": "replace",
                    "path": (
                        f"/spec/template/spec/containers/{git_proxy_container_index}"
                        f"/env/{git_proxy_renku_access_token_env[0]}/value"
                    ),
                    "value": renku_tokens.access_token,
                }
            )
        if git_proxy_container_index is not None and git_proxy_renku_refresh_token_env is not None:
            patches.append(
                {
                    "op": "replace",
                    "path": (
                        f"/spec/template/spec/containers/{git_proxy_container_index}"
                        f"/env/{git_proxy_renku_refresh_token_env[0]}/value"
                    ),
                    "value": renku_tokens.refresh_token,
                },
            )
        if git_clone_container_index is not None and git_clone_renku_access_token_env is not None:
            patches.append(
                {
                    "op": "replace",
                    "path": (
                        f"/spec/template/spec/initContainers/{git_clone_container_index}"
                        f"/env/{git_clone_renku_access_token_env[0]}/value"
                    ),
                    "value": renku_tokens.access_token,
                },
            )
        if secrets_container_index is not None and secrets_renku_access_token_env is not None:
            patches.append(
                {
                    "op": "replace",
                    "path": (
                        f"/spec/template/spec/initContainers/{secrets_container_index}"
                        f"/env/{secrets_renku_access_token_env[0]}/value"
                    ),
                    "value": renku_tokens.access_token,
                },
            )

        return patches

    async def _get(self, name: str, gvk: GVK, safe_username: str | None) -> K8sObject | None:
        """Get a specific object, None is returned if it does not exist."""
        objects = [
            o
            async for o in self.__client.list(
                K8sObjectFilter(
                    gvk=gvk,
                    user_id=safe_username,
                    name=name,
                )
            )
        ]
        if len(objects) == 1:
            return objects[0]

        return None

    async def namespace(self) -> str:
        """Current namespace of the main cluster."""
        client = await self.__client.cluster_by_id(self.cluster_id())
        return client.namespace

    @staticmethod
    def cluster_id() -> ClusterId:
        """Cluster id of the main cluster."""
        return DEFAULT_K8S_CLUSTER

    async def cluster_by_class_id(self, class_id: int | None, api_user: APIUser) -> ClusterConnection:
        """Return the cluster associated with the given resource class id."""
        cluster_id = self.cluster_id()

        if class_id is not None:
            try:
                rp = await self.__rp_repo.get_resource_pool_from_class(api_user, class_id)
                if rp.cluster is not None:
                    cluster_id = rp.cluster.id
            except errors.MissingResourceError:
                pass

        return await self.__client.cluster_by_id(cluster_id)

    async def list_sessions(self, safe_username: str) -> list[AmaltheaSessionV1Alpha1]:
        """Get a list of sessions that belong to a user."""
        sessions = [
            self.__session_type.model_validate(s.manifest)
            async for s in self.__client.list(
                K8sObjectFilter(
                    gvk=self.__session_gvk,
                    user_id=safe_username,
                    label_selector={self.__username_label: safe_username},
                )
            )
        ]
        return sorted(sessions, key=lambda sess: sess.metadata.name)

    async def get_session(self, name: str, safe_username: str) -> AmaltheaSessionV1Alpha1 | None:
        """Get a specific session, None is returned if the session does not exist."""
        session = await self._get(name, self.__session_gvk, safe_username)

        if session is None:
            return None
        return self.__session_type.model_validate(session.manifest)

    async def create_session(self, manifest: AmaltheaSessionV1Alpha1, api_user: APIUser) -> AmaltheaSessionV1Alpha1:
        """Launch a user session."""
        if api_user.id is None:
            raise errors.ProgrammingError(message=f"API user id unset for {api_user}.")

        session_name = manifest.metadata.name

        session = await self.get_session(session_name, api_user.id)
        if session is not None:
            # NOTE: session already exists
            return session

        cluster = await self.cluster_by_class_id(manifest.resource_class_id(), api_user)

        manifest.metadata.labels[self.__username_label] = api_user.id
        session = await self.__client.create(
            K8sObject(
                name=session_name,
                namespace=cluster.namespace,
                cluster=cluster.id,
                gvk=self.__session_gvk,
                user_id=api_user.id,
                manifest=Box(manifest.model_dump(exclude_none=True, mode="json")),
            ),
            refresh=True,
        )

        # NOTE: We wait for the cache to sync with the newly created server
        # With this we wait for the cache to catch up before we return a result.
        def _check_ready(obj: K8sObject | None) -> bool:
            return obj is None or obj.manifest.metadata.get("creationTimestamp") is None

        refreshed_session = await retry_with_exponential_backoff_async(_check_ready)(self.__client.get)(session)
        if refreshed_session is not None:
            session = refreshed_session

        return self.__session_type.model_validate(session.manifest)

    async def patch_session(
        self, session_name: str, safe_username: str, patch: dict[str, Any] | list[dict[str, Any]]
    ) -> AmaltheaSessionV1Alpha1:
        """Patch a session."""
        session = await self._get(session_name, self.__session_gvk, safe_username)
        if session is None:
            raise errors.MissingResourceError(
                message=f"Cannot find session {session_name} for user {safe_username} in order to patch it."
            )

        result = await self.__client.patch(session, patch)
        return self.__session_type.model_validate(result.manifest)

    async def delete_session(self, session_name: str, safe_username: str) -> None:
        """Delete the session."""
        session = await self._get(session_name, self.__session_gvk, safe_username)
        if session is not None:
            await self.__client.delete(session)

    async def get_statefulset(self, session_name: str, safe_username: str) -> StatefulSet | None:
        """Return the statefulset for the given user session."""
        statefulset = await self._get(session_name, GVK.from_kr8s_object(StatefulSet), safe_username)
        if statefulset is None:
            return None

        cluster = await self.__client.cluster_by_id(statefulset.cluster)

        return StatefulSet(
            resource=statefulset.to_api_object(cluster.api), namespace=statefulset.namespace, api=cluster.api
        )

    async def patch_statefulset(
        self, session_name: str, safe_username: str, patch: dict[str, Any] | list[dict[str, Any]]
    ) -> StatefulSet | None:
        """Patch a statefulset."""
        sts = await self.get_statefulset(session_name, safe_username)
        if sts is None:
            return None

        patch_type: str | None = None  # rfc7386 patch
        if isinstance(patch, list):
            patch_type = "json"  # rfc6902 patch

        try:
            await sts.patch(patch=patch, type=patch_type)
        except ServerError as err:
            if err.response is not None and err.response.status_code == 404:
                # NOTE: It can happen potentially that another request or something else
                # deleted the session as this request was going on, in this case we ignore
                # the missing statefulset
                return None
            raise

        return sts

    async def patch_statefulset_tokens(self, session_name: str, renku_tokens: RenkuTokens, safe_username: str) -> None:
        """Patch the Renku and Gitlab access tokens used in a session."""
        sts = await self.get_statefulset(session_name, safe_username)
        if sts is None:
            return
        patches = self._get_statefulset_token_patches(sts, renku_tokens)
        await sts.patch(patch=patches, type="json")

    async def patch_session_tokens(
        self, session_name: str, safe_username: str, renku_tokens: RenkuTokens, gitlab_token: GitlabToken
    ) -> None:
        """Patch the Renku and Gitlab access tokens used in a session."""
        await self.patch_statefulset_tokens(session_name, renku_tokens, safe_username)
        await self.patch_image_pull_secret(session_name, gitlab_token, safe_username)

    async def get_session_logs(
        self, session_name: str, safe_username: str, max_log_lines: int | None = None
    ) -> dict[str, str]:
        """Get the logs from the session."""
        # NOTE: this get_session ensures the user has access to the session, without this you could read someone else's
        #       logs
        session = await self.get_session(session_name, safe_username)
        if session is None:
            raise errors.MissingResourceError(
                message=f"Cannot find session {session_name} for user {safe_username} to retrieve logs."
            )
        pod_name = f"{session_name}-0"
        result = await self._get(pod_name, GVK.from_kr8s_object(Pod), None)

        logs: dict[str, str] = {}
        if result is None:
            return logs

        cluster = await self.__client.cluster_by_id(result.cluster)

        pod = Pod(resource=result.to_api_object(cluster.api), namespace=result.namespace, api=cluster.api)

        containers = [container.name for container in pod.spec.containers + pod.spec.get("initContainers", [])]
        for container in containers:
            try:
                # NOTE: calling pod.logs without a container name set crashes the library
                clogs: list[str] = [clog async for clog in pod.logs(container=container, tail_lines=max_log_lines)]
            except (httpx.ResponseNotRead, httpx.HTTPStatusError):
                # NOTE: This occurs when the container is still starting, but we try to read its logs
                continue
            except NotFoundError as err:
                raise errors.MissingResourceError(message=f"The session pod {pod_name} does not exist.") from err
            except ServerError as err:
                if err.response is not None and err.response.status_code == 400:
                    # NOTE: This occurs when the target container is not yet running, but we try to read its logs
                    continue
                if err.response is not None and err.response.status_code == 404:
                    raise errors.MissingResourceError(message=f"The session pod {pod_name} does not exist.") from err
                raise
            else:
                logs[container] = "\n".join(clogs)
        return logs

    async def patch_image_pull_secret(self, session_name: str, gitlab_token: GitlabToken, safe_username: str) -> None:
        """Patch the image pull secret used in a Renku session."""
        secret_name = f"{session_name}-image-secret"
        result = await self._get(secret_name, GVK.from_kr8s_object(Secret), safe_username)
        if result is None:
            return

        cluster = await self.__client.cluster_by_id(result.cluster)

        secret = Secret(resource=result.to_api_object(cluster.api), namespace=result.namespace, api=cluster.api)

        secret_data = secret.data.to_dict()
        old_docker_config = json.loads(base64.b64decode(secret_data[".dockerconfigjson"]).decode())
        hostname = next(iter(old_docker_config["auths"].keys()), None)
        if not hostname:
            raise errors.ProgrammingError(
                message="Failed to refresh the access credentials in the image pull secret.",
                detail="Please contact a Renku administrator.",
            )
        new_docker_config = {
            "auths": {
                hostname: {
                    "Username": "oauth2",
                    "Password": gitlab_token.access_token,
                    "Email": old_docker_config["auths"][hostname]["Email"],
                }
            }
        }
        patch_path = "/data/.dockerconfigjson"
        patch = [
            {
                "op": "replace",
                "path": patch_path,
                "value": base64.b64encode(json.dumps(new_docker_config).encode()).decode(),
            }
        ]

        await secret.patch(patch, type="json")

    async def create_secret(self, secret: K8sSecret) -> K8sSecret:
        """Create a secret."""

        return await self.__secrets_client.create_secret(secret)

    async def patch_secret(self, secret: K8sObjectMeta, patch: dict[str, Any] | list[dict[str, Any]]) -> K8sSecret:
        """Patch a secret."""

        return await self.__secrets_client.patch_secret(secret, patch)

    async def delete_secret(self, secret: K8sObjectMeta) -> None:
        """Delete a secret."""

        return await self.__secrets_client.delete_secret(secret)

    async def create_or_patch_secret(self, secret: K8sSecret) -> K8sSecret:
        """Create or patch a secret.

        This is equivalent to an upsert operation.
        """
        logger = logging.getLogger(NotebookK8sClient.__name__)
        try:
            result = await self.create_secret(secret)
        except ServerError as e:
            if e.response is None or e.response.status_code != 409:
                raise
            # NOTE: If the response code is 409, it means that the secret already exists
            logger.debug(f"Patching secret {secret.namespace}/{secret.name}")
            result = await self.patch_secret(secret, secret.to_patch())
        return result
