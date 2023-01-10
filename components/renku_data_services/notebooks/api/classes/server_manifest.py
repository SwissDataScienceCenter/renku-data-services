from typing import Any, Dict, List

from ...config import config
from .cloud_storage.existing import ExistingCloudStorage


class UserServerManifest:
    def __init__(self, manifest: Dict[str, Any]) -> None:
        self.manifest = manifest

    @property
    def name(self) -> str:
        return self.manifest["metadata"]["name"]

    @property
    def image(self) -> str:
        return self.manifest["spec"]["jupyterServer"]["image"]

    @property
    def using_default_image(self) -> bool:
        self.image == config.sessions.default_image

    @property
    def server_options(self) -> Dict[str, Any]:
        js = self.manifest
        server_options = {}
        # url
        server_options["defaultUrl"] = js["spec"]["jupyterServer"]["defaultUrl"]
        # disk
        server_options["disk_request"] = js["spec"]["storage"].get("size")
        # NOTE: Amalthea accepts only strings for disk request, but k8s allows bytes as number
        # so try to convert to number if possible
        try:
            server_options["disk_request"] = float(server_options["disk_request"])
        except ValueError:
            pass
        # cpu, memory, gpu, ephemeral storage
        k8s_res_name_xref = {
            "memory": "mem_request",
            "nvidia.com/gpu": "gpu_request",
            "cpu": "cpu_request",
            "ephemeral-storage": "ephemeral-storage",
        }
        js_resources = js["spec"]["jupyterServer"]["resources"]["requests"]
        for k8s_res_name in k8s_res_name_xref.keys():
            if k8s_res_name in js_resources.keys():
                server_options[k8s_res_name_xref[k8s_res_name]] = js_resources[
                    k8s_res_name
                ]
        # adjust ephemeral storage properly based on whether persistent volumes are used
        if "ephemeral-storage" in server_options.keys():
            server_options["ephemeral-storage"] = (
                server_options["ephemeral-storage"]
                if config.sessions.storage.pvs_enabled
                else server_options["disk_request"]
            )
        # lfs auto fetch
        for patches in js["spec"]["patches"]:
            for patch in patches.get("patch", []):
                if (
                    patch.get("path")
                    == "/statefulset/spec/template/spec/initContainers/-"
                ):
                    for env in patch.get("value", {}).get("env", []):
                        if env.get("name") == "GIT_CLONE_LFS_AUTO_FETCH":
                            server_options["lfs_auto_fetch"] = env.get("value") == "1"
        return {
            **config.server_options.defaults,
            **server_options,
        }

    @property
    def annotations(self) -> Dict[str, str]:
        return self.manifest["metadata"]["annotations"]

    @property
    def labels(self) -> Dict[str, str]:
        return self.manifest["metadata"]["labels"]

    @property
    def cloudstorage(self) -> List[ExistingCloudStorage]:
        return ExistingCloudStorage.from_manifest(self.manifest)

    @property
    def server_name(self) -> str:
        return self.manifest["metadata"]["name"]

    @property
    def url(self) -> str:
        host = self.manifest["spec"]["routing"]["host"]
        path = self.manifest["spec"]["routing"]["path"].rstrip("/")
        token = self.manifest["spec"]["auth"].get("token", "")
        url = f"https://{host}{path}"
        if token and len(token) > 0:
            url += f"?token={token}"
        return url
