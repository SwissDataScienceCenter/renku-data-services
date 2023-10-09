import re
from typing import Optional
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from azure.storage.blob import ContainerClient

from ....config import config
from ....errors.user import InvalidCloudStorageUrl
from . import ICloudStorageRequest


class AzureBlobRequest(ICloudStorageRequest):
    def __init__(
        self,
        endpoint: str,
        container: str,
        mount_folder: str,
        source_folder: str,
        credential: Optional[str] = None,
        read_only: bool = True,
    ) -> None:
        self.endpoint = endpoint
        self.container = container
        self.credential = credential
        self._client = ContainerClient(self.endpoint, container, credential=credential)
        parsed_credential = parse_qs(credential)
        self._credentail_is_SAS = (
            parsed_credential != {}
            and ("sv" in parsed_credential or "?sv" in parsed_credential)
            and ("sig" in parsed_credential or "?sig" in parsed_credential)
        )
        self._mount_folder = str(mount_folder).rstrip("/")
        self._source_folder = str(source_folder).rstrip("/")
        self._read_only = read_only

    @property
    def exists(self):
        return self._client.exists()

    @property
    def mount_folder(self) -> str:
        return self._mount_folder

    @property
    def source_folder(self) -> str:
        return self._source_folder

    @property
    def bucket(self) -> str:
        return self.container

    @property
    def storage_account_name(self) -> str:
        parsed_url = urlparse(self.endpoint)
        hostname = parsed_url.hostname
        if hostname is None:
            raise InvalidCloudStorageUrl("The Azure blob storage account url cannot be parsed.")
        # NOTE: Based on details from the docs at:
        # https://learn.microsoft.com/en-us/azure/storage/common/storage-account-overview
        res = re.match(
            r"^([a-z0-9]{3,24})(?:\.blob\.core\.windows\.net|"
            r"\.z[0-9]{2,2}\.blob\.storage\.azure\.net)$",
            hostname,
        )
        if res is None:
            raise InvalidCloudStorageUrl("The Azure blob storage account url cannot be parsed.")
        return res.group(1)

    def get_manifest_patch(self, base_name: str, namespace: str, labels={}, annotations={}):
        secret_name = f"{base_name}-secret"
        volume = {
            "apiVersion": "v1",
            "kind": "PersistentVolume",
            "metadata": {
                "name": base_name,
                "namespace": namespace,
                "annotations": {
                    **annotations,
                    config.session_get_endpoint_annotations.renku_annotation_prefix
                    + "endpoint": self.endpoint,
                },
                "labels": labels,
            },
            "spec": {
                "persistentVolumeReclaimPolicy": "Retain",
                "storageClassName": "azureblob-fuse-premium",
                "mountOptions": [
                    "-o allow_other",
                    "--file-cache-timeout-in-seconds=120",
                ],
                "capacity": {"storage": "1Gi"},
                "accessModes": ["ReadOnlyMany" if self._read_only else "ReadWriteOnce"],
                "csi": {
                    "driver": "blob.csi.azure.com",
                    "readOnly": self._read_only,
                    "volumeHandle": str(uuid4()),
                    "volumeAttributes": {
                        "containerName": self.container,
                    },
                    "nodeStageSecretRef": {
                        "name": secret_name,
                        "namespace": namespace,
                    },
                },
            },
        }
        if self._read_only:
            volume["spec"]["mountOptions"].append("-o ro")
        volume_claim = {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {
                "name": base_name,
                "namespace": namespace,
                "annotations": annotations,
                "labels": labels,
            },
            "spec": {
                "accessModes": ["ReadOnlyMany" if self._read_only else "ReadWriteOnce"],
                "resources": {
                    "requests": {
                        "storage": "1Gi",
                    },
                },
                "volumeName": base_name,
                "storageClassName": "azureblob-fuse-premium",
            },
        }
        patch = {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": f"/{base_name}-pv",
                    "value": volume,
                },
                {
                    "op": "add",
                    "path": f"/{base_name}-pvc",
                    "value": volume_claim,
                },
                # mount dataset into user session
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/containers/0/volumeMounts/-",
                    "value": {
                        "mountPath": self.mount_folder,
                        "name": base_name,
                        "subPath": self.source_folder,
                    },
                },
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/volumes/-",
                    "value": {
                        "name": base_name,
                        "persistentVolumeClaim": {"claimName": base_name},
                    },
                },
            ],
        }
        # add secret for storing access keys for s3
        patch["patch"].append(
            {
                "op": "add",
                "path": f"/{secret_name}",
                "value": {
                    "apiVersion": "v1",
                    "kind": "Secret",
                    "metadata": {
                        "name": secret_name,
                        "namespace": namespace,
                        "labels": labels,
                        "annotations": annotations,
                    },
                    "stringData": {
                        (
                            "azurestorageaccountsastoken"
                            if self._credentail_is_SAS
                            else "azurestorageaccountkey"
                        ): self.credential,
                        "azurestorageaccountname": self.storage_account_name,
                        "azurestorageaccountendpoint": self.endpoint,
                    },
                },
            },
        )
        return patch
