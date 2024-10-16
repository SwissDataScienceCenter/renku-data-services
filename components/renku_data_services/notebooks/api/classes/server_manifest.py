"""Representation of a jupyter server session manifest."""

import contextlib
import json
from typing import Any, Optional, cast

from renku_data_services.errors import errors
from renku_data_services.notebooks.api.classes.cloud_storage.existing import ExistingCloudStorage
from renku_data_services.notebooks.crs import JupyterServerV1Alpha1


class UserServerManifest:
    """Thin wrapper around a jupyter server manifest."""

    def __init__(self, manifest: JupyterServerV1Alpha1, default_image: str, pvs_enabled: bool = True) -> None:
        self.manifest = manifest
        self.default_image = default_image
        self.pvs_enabled = pvs_enabled

    @property
    def name(self) -> str:
        """The name of the server."""
        return self.manifest.metadata.name

    @property
    def image(self) -> str:
        """The image the server is running."""
        if self.manifest.spec is None:
            raise errors.ProgrammingError(message="Unexpected manifest format")
        return self.manifest.spec.jupyterServer.image

    @property
    def using_default_image(self) -> bool:
        """Whether a default image is used or not."""
        return self.image == self.default_image

    @property
    def server_options(self) -> dict[str, str | int | float]:
        """Extract the server options from a manifest."""
        js = self.manifest
        if js.spec is None:
            raise errors.ProgrammingError(message="Unexpected manifest format")
        server_options: dict[str, str | int | float] = {}
        # url
        server_options["defaultUrl"] = js.spec.jupyterServer.defaultUrl
        # disk
        server_options["disk_request"] = js.spec.storage.size
        # NOTE: Amalthea accepts only strings for disk request, but k8s allows bytes as number
        # so try to convert to number if possible
        with contextlib.suppress(ValueError):
            server_options["disk_request"] = float(server_options["disk_request"])
        # cpu, memory, gpu, ephemeral storage
        k8s_res_name_xref = {
            "memory": "mem_request",
            "nvidia.com/gpu": "gpu_request",
            "cpu": "cpu_request",
            "ephemeral-storage": "ephemeral-storage",
        }
        js_resources = js.spec.jupyterServer.resources["requests"]
        for k8s_res_name in k8s_res_name_xref:
            if k8s_res_name in js_resources:
                server_options[k8s_res_name_xref[k8s_res_name]] = js_resources[k8s_res_name]
        # adjust ephemeral storage properly based on whether persistent volumes are used
        if "ephemeral-storage" in server_options:
            server_options["ephemeral-storage"] = (
                server_options["ephemeral-storage"] if self.pvs_enabled else server_options["disk_request"]
            )
        # lfs auto fetch
        for patches in js.spec.patches:
            for patch in cast(dict, patches.patch):
                if patch.get("path") == "/statefulset/spec/template/spec/initContainers/-":
                    for env in patch.get("value", {}).get("env", []):
                        if env.get("name") == "GIT_CLONE_LFS_AUTO_FETCH":
                            server_options["lfs_auto_fetch"] = env.get("value") == "1"
        return server_options

    @property
    def annotations(self) -> dict[str, str]:
        """Extract the manifest annotations."""
        return self.manifest.metadata.annotations

    @property
    def labels(self) -> dict[str, str]:
        """Extract the manifest labels."""
        return self.manifest.metadata.labels

    @property
    def cloudstorage(self) -> list[ExistingCloudStorage]:
        """Get the cloud storage."""
        return ExistingCloudStorage.from_manifest(self.manifest)

    @property
    def server_name(self) -> str:
        """Get the server name."""
        return self.manifest.metadata.name

    @property
    def hibernation(self) -> Optional[dict[str, Any]]:
        """Return hibernation annotation."""
        hibernation = self.manifest.metadata.annotations.get("renku.io/hibernation")
        return json.loads(hibernation) if hibernation else None

    @property
    def dirty(self) -> bool:
        """Return True if server is dirty, i.e. if it has unsaved data in the git repository."""
        is_dirty = False
        if self.hibernation:
            dirty_annotation = self.hibernation.get("dirty")
            is_dirty = (isinstance(dirty_annotation, bool) and is_dirty) or (
                isinstance(dirty_annotation, str) and dirty_annotation.lower() == "false"
            )
        return is_dirty

    @property
    def hibernation_commit(self) -> Optional[str]:
        """Return hibernated server commit if any."""
        hibernation = self.hibernation or {}
        return hibernation.get("commit")

    @property
    def hibernation_branch(self) -> Optional[str]:
        """Return hibernated server branch if any."""
        hibernation = self.hibernation or {}
        return hibernation.get("branch")

    @property
    def url(self) -> str:
        """Return the url where the user can access the session."""
        if self.manifest.spec is None:
            raise errors.ProgrammingError(message="Unexpected manifest format")
        host = self.manifest.spec.routing.host
        path = self.manifest.spec.routing.path.rstrip("/")
        token = self.manifest.spec.auth.token or ""
        url = f"https://{host}{path}"
        if token and len(token) > 0:
            url += f"?token={token}"
        return url
