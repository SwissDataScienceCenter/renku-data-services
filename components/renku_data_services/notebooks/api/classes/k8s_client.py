"""An abstraction over the kr8s kubernetes client and the k8s-watcher."""

import base64
import json
from contextlib import suppress
from typing import Any, Generic, Optional, TypeVar, cast

import httpx
import kubernetes
from box import Box
from kr8s import NotFoundError, ServerError
from kr8s.asyncio.objects import APIObject, Pod, Secret, StatefulSet
from kubernetes.client import V1Secret

from renku_data_services.base_models import APIUser
from renku_data_services.crc.db import ResourcePoolRepository
from renku_data_services.errors import errors
from renku_data_services.k8s.clients import K8sClusterClientsPool
from renku_data_services.k8s.models import Cluster, ClusterId, K8sObject, K8sObjectFilter, K8sObjectMeta
from renku_data_services.k8s_watcher.core import APIObjectInCluster
from renku_data_services.notebooks.api.classes.auth import GitlabToken, RenkuTokens
from renku_data_services.notebooks.constants import JUPYTER_SESSION_KIND, JUPYTER_SESSION_VERSION
from renku_data_services.notebooks.crs import AmaltheaSessionV1Alpha1, JupyterServerV1Alpha1
from renku_data_services.notebooks.errors.programming import ProgrammingError
from renku_data_services.notebooks.util.kubernetes_ import find_env_var

DEFAULT_K8S_CLUSTER: ClusterId = ClusterId("renkulab")
sanitizer = kubernetes.client.ApiClient().sanitize_for_serialization


# NOTE The type ignore below is because the kr8s library has no type stubs, they claim pyright better handles type hints
class JupyterServerV1Alpha1Kr8s(APIObject):
    """Spec for jupyter servers used by the k8s client."""

    kind: str = JUPYTER_SESSION_KIND
    version: str = JUPYTER_SESSION_VERSION
    namespaced: bool = True
    plural: str = "jupyterservers"
    singular: str = "jupyterserver"
    scalable: bool = False
    endpoint: str = "jupyterservers"


_SessionType = TypeVar("_SessionType", JupyterServerV1Alpha1, AmaltheaSessionV1Alpha1)


class NotebookK8sClient(Generic[_SessionType]):
    """A K8s Client for Notebooks."""

    def __init__(
        self,
        client: K8sClusterClientsPool,
        rp_repo: ResourcePoolRepository,
        server_type: type[_SessionType],
        server_kind: str,
        server_api_version: str,
        username_label: str,
    ) -> None:
        self.client = client
        self.rp_repo = rp_repo
        self.server_type: type[_SessionType] = server_type
        self.server_kind = server_kind
        self.server_api_version = server_api_version
        self.username_label = username_label

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

    async def _get(self, name: str, kind: str, version: str, safe_username: str | None) -> K8sObject | None:
        """Get a specific object, None is returned if it does not exist."""
        objects = [
            o
            async for o in self.client.list(
                K8sObjectFilter(
                    kind=kind,
                    version=version,
                    user_id=safe_username,
                    name=name,
                )
            )
        ]
        if len(objects) == 1:
            return objects[0]

        return None

    def namespace(self) -> str:
        """Current namespace of the main cluster."""
        return self.client.cluster_by_id(self.cluster_id()).namespace

    @staticmethod
    def cluster_id() -> ClusterId:
        """Cluster id of the main cluster."""
        return DEFAULT_K8S_CLUSTER

    async def cluster_name_by_class_id(self, class_id: int | None, api_user: APIUser) -> str:
        """Retrieve the cluster name given the resource class id."""
        # If the config_name is not set or not found, fall back on the default cluster.
        name = str(self.cluster_id())

        if class_id is not None:
            try:
                rp = await self.rp_repo.get_resource_pool_from_class(api_user, class_id)
                if rp.cluster is not None:
                    name = rp.cluster.config_name
            except errors.MissingResourceError:
                pass

        return name

    async def cluster_by_class_id(self, class_id: int | None, api_user: APIUser) -> Cluster:
        """Return the cluster associated with the given resource class id."""
        return self.client.cluster_by_name(await self.cluster_name_by_class_id(class_id, api_user))

    async def list_servers(self, safe_username: str) -> list[_SessionType]:
        """Get a list of servers that belong to a user."""
        return [
            self.server_type.model_validate(s.manifest)
            async for s in self.client.list(
                K8sObjectFilter(
                    kind=self.server_kind,
                    version=self.server_api_version,
                    user_id=safe_username,
                    label_selector={self.username_label: safe_username},
                )
            )
        ]

    async def get_server(self, name: str, safe_username: str) -> _SessionType | None:
        """Get a specific server, None is returned if the server does not exist."""
        server = await self._get(name, self.server_kind, self.server_api_version, safe_username)

        if server is None:
            return None
        return self.server_type.model_validate(server.manifest)

    async def create_server(self, manifest: _SessionType, api_user: APIUser) -> _SessionType:
        """Launch a user session."""
        if api_user.id is None:
            raise ProgrammingError(message=f"API user id un set for {api_user}.")

        server_name = manifest.metadata.name

        server = await self.get_server(server_name, api_user.id)
        if server:
            # NOTE: server already exists
            return server

        cluster = await self.cluster_by_class_id(manifest.resource_class_id(), api_user)

        manifest.metadata.labels[self.username_label] = api_user.id
        session = await self.client.create(
            K8sObject(
                name=server_name,
                namespace=cluster.namespace,
                cluster=cluster.id,
                kind=self.server_kind,
                version=self.server_api_version,
                user_id=api_user.id,
                manifest=Box(manifest.model_dump(exclude_none=True, mode="json")),
            )
        )

        return self.server_type.model_validate(session.manifest)

    async def patch_server(
        self, server_name: str, safe_username: str, patch: dict[str, Any] | list[dict[str, Any]]
    ) -> _SessionType:
        """Patch a server."""
        server = await self._get(server_name, self.server_kind, self.server_api_version, safe_username)
        if server is None:
            raise errors.MissingResourceError(
                message=f"Cannot find server {server_name} for user {safe_username} in order to patch it."
            )

        result = await self.client.patch(server, patch)
        return self.server_type.model_validate(result.manifest)

    async def delete_server(self, server_name: str, safe_username: str) -> None:
        """Delete the server."""
        server = await self._get(server_name, self.server_kind, self.server_api_version, safe_username)
        if server is not None:
            await self.client.delete(server)

    async def get_statefulset(self, server_name: str, safe_username: str) -> StatefulSet | None:
        """Return the statefulset for the given user session."""
        statefulset = await self._get(server_name, StatefulSet.kind, StatefulSet.version, safe_username)
        if statefulset is None:
            return None

        cluster = self.client.cluster_by_id(statefulset.cluster)
        if cluster is None:
            return None

        api_obj_in_cluster = APIObjectInCluster.from_k8s_object(statefulset, cluster.api)
        return StatefulSet(resource=api_obj_in_cluster.obj, namespace=statefulset.meta.namespace, api=cluster.api)

    async def patch_statefulset(
        self, server_name: str, safe_username: str, patch: dict[str, Any] | list[dict[str, Any]]
    ) -> StatefulSet | None:
        """Patch a statefulset."""
        sts = await self.get_statefulset(server_name, safe_username)
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

    async def patch_statefulset_tokens(self, server_name: str, renku_tokens: RenkuTokens, safe_username: str) -> None:
        """Patch the Renku and Gitlab access tokens used in a session."""
        sts = await self.get_statefulset(server_name, safe_username)
        if sts is None:
            return
        patches = self._get_statefulset_token_patches(sts, renku_tokens)
        await sts.patch(patch=patches, type="json")

    async def patch_server_tokens(
        self, server_name: str, safe_username: str, renku_tokens: RenkuTokens, gitlab_token: GitlabToken
    ) -> None:
        """Patch the Renku and Gitlab access tokens used in a session."""
        await self.patch_statefulset_tokens(server_name, renku_tokens, safe_username)
        await self.patch_image_pull_secret(server_name, gitlab_token, safe_username)

    async def get_server_logs(
        self, server_name: str, safe_username: str, max_log_lines: Optional[int] = None
    ) -> dict[str, str]:
        """Get the logs from the server."""
        # NOTE: this get_server ensures the user has access to the server, without this you could read someone else's
        #       logs
        server = await self.get_server(server_name, safe_username)
        if server is None:
            raise errors.MissingResourceError(
                message=f"Cannot find server {server_name} for user {safe_username} to retrieve logs."
            )
        pod_name = f"{server_name}-0"
        result = await self._get(pod_name, Pod.kind, Pod.version, None)

        logs: dict[str, str] = {}
        if result is None:
            return logs

        cluster = self.client.cluster_by_id(result.cluster)
        if cluster is None:
            return logs

        obj = APIObjectInCluster.from_k8s_object(result, cluster.api)
        pod = Pod(resource=obj.obj, namespace=obj.obj.namespace, api=cluster.api)

        containers = [container.name for container in pod.spec.containers + pod.spec.get("initContainers", [])]
        for container in containers:
            try:
                # NOTE: calling pod.logs without a container name set crashes the library
                clogs: list[str] = [clog async for clog in pod.logs(container=container, tail_lines=max_log_lines)]
            except httpx.ResponseNotRead:
                # NOTE: This occurs when the container is still starting, but we try to read its logs
                continue
            except NotFoundError:
                raise errors.MissingResourceError(message=f"The session pod {pod_name} does not exist.")
            except ServerError as err:
                if err.status == 404:
                    raise errors.MissingResourceError(message=f"The session pod {pod_name} does not exist.")
                raise
            else:
                logs[container] = "\n".join(clogs)
        return logs

    async def patch_image_pull_secret(self, server_name: str, gitlab_token: GitlabToken, safe_username: str) -> None:
        """Patch the image pull secret used in a Renku session."""
        secret_name = f"{server_name}-image-secret"
        result = await self._get(secret_name, Secret.kind, Secret.version, safe_username)
        if result is None:
            return

        cluster = self.client.cluster_by_id(result.cluster)
        if cluster is None:
            return

        api_obj_in_cluster = APIObjectInCluster.from_k8s_object(result, cluster.api)
        secret = Secret(resource=api_obj_in_cluster.obj, namespace=api_obj_in_cluster.obj.namespace, api=cluster.api)

        secret_data = secret.data.to_dict()
        old_docker_config = json.loads(base64.b64decode(secret_data[".dockerconfigjson"]).decode())
        hostname = next(iter(old_docker_config["auths"].keys()), None)
        if not hostname:
            raise ProgrammingError(
                "Failed to refresh the access credentials in the image pull secret.",
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

    async def create_secret(self, secret: V1Secret) -> V1Secret:
        """Create a secret."""
        # TODO: LSA Does not break current code, but bad, as it may be different based on the cluster
        assert secret.metadata is not None
        secret_obj = K8sObject(
            name=secret.metadata.name,
            namespace=self.namespace(),
            cluster=self.cluster_id(),
            kind=Secret.kind,
            version=Secret.version,
            manifest=Box(sanitizer(secret)),
        )
        try:
            result = await self.client.create(secret_obj)
        except ServerError as err:
            if err.response and err.response.status_code == 409:
                annotations: Box | None = secret_obj.manifest.metadata.get("annotations")
                labels: Box | None = secret_obj.manifest.metadata.get("labels")
                patches = [
                    {
                        "op": "replace",
                        "path": "/data",
                        "value": secret.data or {},
                    },
                    {
                        "op": "replace",
                        "path": "/stringData",
                        "value": secret.string_data or {},
                    },
                    {
                        "op": "replace",
                        "path": "/metadata/annotations",
                        "value": annotations.to_dict() if annotations is not None else {},
                    },
                    {
                        "op": "replace",
                        "path": "/metadata/labels",
                        "value": labels.to_dict() if labels is not None else {},
                    },
                ]
                result = await self.client.patch(secret_obj, patches)
            else:
                raise
        return V1Secret(
            metadata=result.manifest.metadata,
            data=result.manifest.get("data", {}),
            string_data=result.manifest.get("stringData", {}),
            type=result.manifest.get("type"),
        )

    async def delete_secret(self, name: str) -> None:
        """Delete a secret."""
        return await self.client.delete(
            # TODO: LSA Does not break current code, but bad, as it may be different based on the cluster
            K8sObjectMeta(
                name=name,
                namespace=self.namespace(),
                cluster=self.cluster_id(),
                kind=Secret.kind,
                version=Secret.version,
            )
        )

    async def patch_secret(self, name: str, patch: dict[str, Any] | list[dict[str, Any]]) -> None:
        """Patch a secret."""
        # TODO: LSA Does not break current code, but bad, as it may be different based on the cluster
        result = await self.client.get(
            K8sObjectMeta(
                name=name,
                namespace=self.namespace(),
                cluster=self.cluster_id(),
                kind=Secret.kind,
                version=Secret.version,
            )
        )
        if result is None:
            raise errors.MissingResourceError(message=f"Cannot find secret {name}.")
        secret = result
        assert isinstance(secret, Secret)

        patch_type: str | None = None  # rfc7386 patch
        if isinstance(patch, list):
            patch_type = "json"  # rfc6902 patch

        with suppress(NotFoundError):
            await secret.patch(patch, type=patch_type)
