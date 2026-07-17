"""K8s client wrapper for Renku apps."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime
from hashlib import md5
from pathlib import PurePosixPath
from typing import Any

from ulid import ULID

from renku_data_services.crc.db import ClusterRepository
from renku_data_services.crc.models import ResourceClass
from renku_data_services.data_connectors.models import DataConnectorWithSecrets
from renku_data_services.k8s.clients import K8sClusterClientsPool
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER, DUMMY_RENKU_APP_USER_ID, ClusterId
from renku_data_services.k8s.models import GVK, ClusterConnection, K8sObjectFilter, K8sObjectMeta, sanitizer
from renku_data_services.notebooks.api.schemas.cloud_storage import RCloneStorage
from renku_data_services.notebooks.crs import Affinity, Toleration
from renku_data_services.notebooks.utils import (
    node_affinity_from_resource_class,
    tolerations_from_resource_class,
)
from renku_data_services.project.models import Project
from renku_data_services.renku_apps.cr_knative_service import Condition
from renku_data_services.renku_apps.crs import KnativeService
from renku_data_services.renku_apps.models import AppRuntimeState
from renku_data_services.session.models import SessionLauncher

KNATIVE_SERVICE_GVK = GVK(kind="Service", group="serving.knative.dev", version="v1")
_SECRET_GVK = GVK(kind="Secret", version="v1")
_PVC_GVK = GVK(kind="PersistentVolumeClaim", version="v1")

_DEFAULT_WORK_DIR = PurePosixPath("/home/jovyan")

_MAX_SCALE_ANNOTATION = "autoscaling.knative.dev/max-scale"
_MAX_SCALE_RUNNING = "3"
_MAX_SCALE_HIBERNATED = "0"

_APP_AUTOSCALING_ANNOTATIONS = {
    "autoscaling.knative.dev/min-scale": "0",
    _MAX_SCALE_ANNOTATION: _MAX_SCALE_RUNNING,
    "autoscaling.knative.dev/scale-to-zero-pod-retention-period": "2m",
}


def _generate_app_name(project: Project, session_launcher: SessionLauncher) -> str:
    """Generate a DNS-1035 label name for an app."""
    launcher_id_slice = str(session_launcher.id)[18:26].lower()
    return f"{project.slug.lower()[:54]}-{launcher_id_slice}"


def _data_source_base_name(app_name: str) -> str:
    """Bounded, DNS-1123-safe base for an app's data-connector resource names."""
    digest = md5(app_name.encode(), usedforsecurity=False).hexdigest()
    return f"{app_name[:12].rstrip('-')}-{digest[:12]}"


@dataclass
class _AppDataConnectorResources:
    """The k8s manifests needed to mount one data connector into an app."""

    name: str
    secret: dict[str, Any]
    pvc: dict[str, Any]
    volume: dict[str, Any]
    volume_mount: dict[str, Any]


def _build_data_connector_resources(
    data_connectors: list[DataConnectorWithSecrets],
    base_name: str,
    namespace: str,
    work_dir: PurePosixPath,
    storage_class: str,
    labels: dict[str, str],
) -> list[_AppDataConnectorResources]:
    """Build the csi-rclone Secret/PVC/volume manifests for each mountable connector."""
    resources: list[_AppDataConnectorResources] = []
    for dc_with_secrets in data_connectors:
        dc = dc_with_secrets.data_connector
        resource_name = f"{base_name}-ds-{str(dc.id).lower()}"
        target_path = PurePosixPath(dc.storage.target_path)
        mount_folder = target_path.as_posix() if target_path.is_absolute() else (work_dir / target_path).as_posix()
        storage = RCloneStorage(
            source_path=dc.storage.source_path,
            configuration=dict(dc.storage.configuration),
            readonly=True,
            mount_folder=mount_folder,
            name=dc.name,
            secrets={},
            storage_class=storage_class,
        )
        resources.append(
            _AppDataConnectorResources(
                name=resource_name,
                secret=sanitizer(storage.secret(resource_name, namespace, labels=labels)),
                pvc=sanitizer(storage.pvc(resource_name, namespace, labels=labels)),
                volume=sanitizer(storage.volume(resource_name)),
                volume_mount=sanitizer(storage.volume_mount(resource_name)),
            )
        )
    return resources


class RenkuAppsK8sClient:
    """K8s client for Renku apps operations."""

    def __init__(
        self,
        client: K8sClusterClientsPool,
        cluster_repo: ClusterRepository,
        storage_class: str,
        default_affinity: Affinity,
        default_tolerations: list[Toleration],
        cluster_id: ClusterId = DEFAULT_K8S_CLUSTER,
    ) -> None:
        self.__client = client
        self.__cluster_repo = cluster_repo
        self.__storage_class = storage_class
        self.__default_affinity = default_affinity
        self.__default_tolerations = default_tolerations
        self.__cluster_id = cluster_id

    async def create_app_deployment(
        self,
        session_launcher: SessionLauncher,
        resource_class: ResourceClass | None,
        project: Project,
        data_connectors: list[DataConnectorWithSecrets],
    ) -> AppRuntimeState:
        """Create a deployment for the given app and return its observed runtime state."""
        cluster = await self.__client.cluster_by_id(self.__cluster_id)
        app_name = _generate_app_name(project, session_launcher)
        labels = _app_labels(session_launcher, project)

        work_dir = session_launcher.environment.working_directory or _DEFAULT_WORK_DIR
        dc_resources = _build_data_connector_resources(
            data_connectors,
            base_name=_data_source_base_name(app_name),
            namespace=cluster.namespace,
            work_dir=work_dir,
            storage_class=self.__storage_class,
            labels=labels,
        )

        affinity, tolerations = _scheduling_from_resource_class(
            resource_class, self.__default_affinity, self.__default_tolerations
        )
        manifest = _build_app_deployment_manifest(
            session_launcher,
            app_name,
            resource_class,
            project,
            labels=labels,
            volumes=[r.volume for r in dc_resources],
            volume_mounts=[r.volume_mount for r in dc_resources],
            affinity=affinity,
            tolerations=tolerations,
        )
        meta = K8sObjectMeta(
            name=app_name,
            namespace=cluster.namespace,
            cluster=cluster.id,
            gvk=KNATIVE_SERVICE_GVK,
            user_id=DUMMY_RENKU_APP_USER_ID,
        )
        created = await self.__client.create(
            meta.with_manifest(manifest.model_dump(exclude_none=True, mode="json")), refresh=True
        )

        owner_reference = _service_owner_reference(app_name, str(created.manifest.metadata.uid))
        for resource in dc_resources:
            await self._create_owned(resource.secret, _SECRET_GVK, resource.name, cluster, owner_reference)
            await self._create_owned(resource.pvc, _PVC_GVK, resource.name, cluster, owner_reference)

        return _extract_runtime_state(KnativeService.model_validate(created.manifest))

    async def _create_owned(
        self,
        manifest: dict[str, Any],
        gvk: GVK,
        name: str,
        cluster: ClusterConnection,
        owner_reference: dict[str, Any],
    ) -> None:
        """Create a Service-owned resource (its PVC/Secret) with the owner reference set."""
        manifest.setdefault("metadata", {})["ownerReferences"] = [owner_reference]
        meta = K8sObjectMeta(
            name=name,
            namespace=cluster.namespace,
            cluster=cluster.id,
            gvk=gvk,
            user_id=DUMMY_RENKU_APP_USER_ID,
        )
        await self.__client.create(meta.with_manifest(manifest), refresh=False)

    async def get_app_deployment(self, app_name: str) -> AppRuntimeState | None:
        """Get the runtime state for the given app name, or None if it does not exist."""
        cluster = await self.__client.cluster_by_id(self.__cluster_id)
        meta = K8sObjectMeta(
            name=app_name,
            namespace=cluster.namespace,
            cluster=cluster.id,
            gvk=KNATIVE_SERVICE_GVK,
            user_id=DUMMY_RENKU_APP_USER_ID,
        )
        obj = await self.__client.get(meta)
        if obj is None:
            return None
        return _extract_runtime_state(KnativeService.model_validate(obj.manifest))

    async def get_app_deployment_for_project(self, project_id: ULID) -> AppRuntimeState | None:
        """Get an existing app in the project (matched by project-id label), or None if none exist."""
        async for runtime_state in self.list_app_deployments(project_id):
            return runtime_state
        return None

    async def get_app_deployment_for_launcher(self, launcher_id: ULID) -> AppRuntimeState | None:
        """Get the runtime state for the launcher's app via its label, or None if it does not exist."""
        cluster = await self.__client.cluster_by_id(self.__cluster_id)
        obj_filter = K8sObjectFilter(
            name=None,
            namespace=cluster.namespace,
            cluster=cluster.id,
            gvk=KNATIVE_SERVICE_GVK,
            user_id=DUMMY_RENKU_APP_USER_ID,
            label_selector={"renku.io/launcher-id": str(launcher_id)},
        )
        async for obj in self.__client.list(obj_filter):
            return _extract_runtime_state(KnativeService.model_validate(obj.manifest))
        return None

    async def delete_app_deployment(self, app_name: str) -> None:
        """Delete the deployment for the given app name."""
        cluster = await self.__client.cluster_by_id(self.__cluster_id)
        meta = K8sObjectMeta(
            name=app_name,
            namespace=cluster.namespace,
            cluster=cluster.id,
            gvk=KNATIVE_SERVICE_GVK,
            user_id=DUMMY_RENKU_APP_USER_ID,
        )
        await self.__client.delete(meta)

    async def list_app_deployments(self, project_id: ULID | None = None) -> AsyncGenerator[AppRuntimeState, None]:
        """List all app deployments."""
        cluster = await self.__client.cluster_by_id(self.__cluster_id)
        obj_filter = K8sObjectFilter(
            name=None,
            namespace=cluster.namespace,
            cluster=cluster.id,
            gvk=KNATIVE_SERVICE_GVK,
            user_id=DUMMY_RENKU_APP_USER_ID,
            label_selector={"renku.io/project-id": str(project_id)} if project_id is not None else None,
        )
        async for obj in self.__client.list(obj_filter):
            yield _extract_runtime_state(KnativeService.model_validate(obj.manifest))

    async def hibernate_app_deployment(self, app_name: str) -> AppRuntimeState:
        """Hibernate the app by patching its max-scale annotation to zero."""
        return await self._patch_max_scale(app_name, _MAX_SCALE_HIBERNATED)

    async def resume_app_deployment(self, app_name: str) -> AppRuntimeState:
        """Resume the app by restoring the default max-scale annotation."""
        return await self._patch_max_scale(app_name, _MAX_SCALE_RUNNING)

    async def set_app_deployment_resources(self, app_name: str, resource_class: ResourceClass) -> AppRuntimeState:
        """Update the container resources of the app to match the given resource class."""
        cluster = await self.__client.cluster_by_id(self.__cluster_id)
        meta = K8sObjectMeta(
            name=app_name,
            namespace=cluster.namespace,
            cluster=cluster.id,
            gvk=KNATIVE_SERVICE_GVK,
            user_id=DUMMY_RENKU_APP_USER_ID,
        )
        # TODO: This JSON patch targets the container by position (containers/0). Once apps run more
        # than one container this becomes fragile and should be a strategic merge patch keyed on the
        # container name. Our kr8s wrapper only emits json/merge patches (never strategic merge), so
        # switching requires extending the wrapper first.
        patch_body: list[dict[str, Any]] = [
            {
                "op": "replace",
                "path": "/spec/template/spec/containers/0/resources",
                "value": _resources_from_resource_class(resource_class),
            }
        ]
        updated = await self.__client.patch(meta, patch_body)
        return _extract_runtime_state(KnativeService.model_validate(updated.manifest))

    async def _patch_max_scale(self, app_name: str, max_scale: str) -> AppRuntimeState:
        cluster = await self.__client.cluster_by_id(self.__cluster_id)
        meta = K8sObjectMeta(
            name=app_name,
            namespace=cluster.namespace,
            cluster=cluster.id,
            gvk=KNATIVE_SERVICE_GVK,
            user_id=DUMMY_RENKU_APP_USER_ID,
        )
        patch_body: dict[str, Any] = {
            "spec": {"template": {"metadata": {"annotations": {_MAX_SCALE_ANNOTATION: max_scale}}}}
        }
        updated = await self.__client.patch(meta, patch_body)
        return _extract_runtime_state(KnativeService.model_validate(updated.manifest))


def _resources_from_resource_class(resource_class: ResourceClass) -> dict[str, Any]:
    """Build a k8s container resources block from a resource class."""
    return {
        "requests": {
            "cpu": f"{round(resource_class.cpu * 1000)}m",
            "memory": f"{resource_class.memory}Gi",
        },
        "limits": {"memory": f"{resource_class.memory}Gi"},
    }


def _app_labels(session_launcher: SessionLauncher, project: Project) -> dict[str, str]:
    """Labels shared by an app's Knative Service and its owned data-connector resources."""
    return {
        "renku.io/safe-username": DUMMY_RENKU_APP_USER_ID,
        "renku.io/project-slug": project.slug.lower(),
        "renku.io/project-namespace": project.namespace.path.serialize().replace("/", "-").lower(),
        "renku.io/project-id": str(project.id),
        "renku.io/project-id-slug": str(project.id)[18:26].lower(),
        "renku.io/launcher-id": str(session_launcher.id),
    }


def _service_owner_reference(app_name: str, uid: str) -> dict[str, Any]:
    """Owner reference making the app's Knative Service the owner of its PVC/Secret."""
    return {
        "apiVersion": KNATIVE_SERVICE_GVK.group_version,
        "kind": KNATIVE_SERVICE_GVK.kind,
        "name": app_name,
        "uid": uid,
        "controller": True,
        "blockOwnerDeletion": True,
    }


def _scheduling_from_resource_class(
    resource_class: ResourceClass | None,
    default_affinity: Affinity,
    default_tolerations: list[Toleration],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Derive the app pod's node affinity and tolerations from the resource class, mirroring sessions."""
    if resource_class is not None:
        affinity = node_affinity_from_resource_class(resource_class, default_affinity)
        tolerations = tolerations_from_resource_class(resource_class, default_tolerations)
    else:
        affinity = default_affinity
        tolerations = default_tolerations

    affinity_dict = None if affinity.is_empty else affinity.model_dump(exclude_none=True, mode="json")
    toleration_dicts = [tol.model_dump(exclude_none=True, mode="json") for tol in tolerations]
    return affinity_dict, toleration_dicts


def _build_app_deployment_manifest(
    session_launcher: SessionLauncher,
    app_name: str,
    resource_class: ResourceClass | None,
    project: Project,
    labels: dict[str, str],
    volumes: list[dict[str, Any]],
    volume_mounts: list[dict[str, Any]],
    affinity: dict[str, Any] | None,
    tolerations: list[dict[str, Any]],
) -> KnativeService:
    """Build a Knative Service manifest derived from the session launcher."""
    environment = session_launcher.environment

    container: dict[str, Any] = {
        "image": environment.container_image,
        "ports": [{"containerPort": environment.port}],
        "securityContext": {
            "runAsUser": environment.uid,
            "runAsGroup": environment.gid,
        },
    }
    if resource_class is not None:
        container["resources"] = _resources_from_resource_class(resource_class)

    # Runtime contract: the app must bind to the same port Knative routes/probes
    # (``containerPort`` above). We surface it as $RENKU_SESSION_PORT so the app can
    # read it (e.g. from a Procfile). This mirrors the AmaltheaSession path in
    # ``notebooks.core_sessions``; without it the buildpack default (8000) wins and
    # the app binds a port Knative never probes, so the revision never becomes ready.
    # System-controlled vars come first; user-defined vars are appended and are not
    # allowed to override them.
    env: list[dict[str, str]] = [
        {"name": "RENKU_SESSION_IP", "value": "0.0.0.0"},  # nosec B104
        {"name": "RENKU_SESSION_PORT", "value": str(environment.port)},
    ]
    reserved_names = {var["name"] for var in env}
    env.extend(
        {"name": var.name, "value": var.value or ""}
        for var in session_launcher.env_variables or []
        if var.name not in reserved_names
    )
    container["env"] = env
    if environment.command:
        container["command"] = environment.command
    if environment.args:
        container["args"] = environment.args
    if environment.working_directory is not None:
        container["workingDir"] = str(environment.working_directory)
    if volume_mounts:
        container["volumeMounts"] = volume_mounts

    pod_spec: dict[str, Any] = {"containers": [container]}
    if volumes:
        pod_spec["volumes"] = volumes
    if affinity:
        pod_spec["affinity"] = affinity
    if tolerations:
        pod_spec["tolerations"] = tolerations

    return KnativeService.model_validate(
        {
            "apiVersion": "serving.knative.dev/v1",
            "kind": "Service",
            "metadata": {
                "name": app_name,
                "labels": labels,
            },
            "spec": {
                "template": {
                    "metadata": {
                        "labels": labels,
                        "annotations": _APP_AUTOSCALING_ANNOTATIONS,
                    },
                    "spec": pod_spec,
                },
            },
        }
    )


def _url(knative_service: KnativeService) -> str | None:
    """Get the public URL Knative assigned to the service, or None if it is not yet routed."""
    if knative_service.status is None:
        return None
    return knative_service.status.url


def _ready_condition(knative_service: KnativeService) -> Condition | None:
    """Get the Ready condition from a Knative service, or None if it doesn't exist."""
    if knative_service.status is None or not knative_service.status.conditions:
        return None
    return next((c for c in knative_service.status.conditions if c.type == "Ready"), None)


def _started_at(knative_service: KnativeService) -> datetime | None:
    """Get the time the Knative service became Ready, or None if not yet ready."""
    ready = _ready_condition(knative_service)
    if ready is None or ready.status != "True" or ready.lastTransitionTime is None:
        return None
    return datetime.fromisoformat(ready.lastTransitionTime)


def _is_hibernated(knative_service: KnativeService) -> bool:
    """Determine if the Knative service is hibernated based on its annotations."""
    if (
        knative_service.spec is None
        or knative_service.spec.template is None
        or knative_service.spec.template.metadata is None
        or knative_service.spec.template.metadata.annotations is None
    ):
        return False
    max_scale = knative_service.spec.template.metadata.annotations.get(_MAX_SCALE_ANNOTATION)
    return max_scale == _MAX_SCALE_HIBERNATED


def _container_image(knative_service: KnativeService) -> str | None:
    """Get the container image actually configured on the Knative service, or None if absent."""
    if (
        knative_service.spec is None
        or knative_service.spec.template is None
        or knative_service.spec.template.spec is None
        or not knative_service.spec.template.spec.containers
    ):
        return None
    return knative_service.spec.template.spec.containers[0].image


def _extract_runtime_state(knative_service: KnativeService) -> AppRuntimeState:
    """Read app runtime state primitives off a Knative Service."""
    ready = _ready_condition(knative_service)
    return AppRuntimeState(
        name=knative_service.metadata.name,
        launcher_id=knative_service.launcher_id,
        project_id=knative_service.project_id,
        ready_status=ready.status if ready is not None else None,
        ready_reason=ready.reason if ready is not None else None,
        is_hibernated=_is_hibernated(knative_service),
        image=_container_image(knative_service),
        url=_url(knative_service),
        started_at=_started_at(knative_service),
    )
