"""Schema for cloudstorage config."""

import json
from configparser import ConfigParser
from io import StringIO
from pathlib import PurePosixPath
from typing import Any, Final, Optional, Protocol, Self

from kubernetes import client
from marshmallow import EXCLUDE, Schema, ValidationError, fields, validates_schema

from renku_data_services.notebooks.api.classes.cloud_storage import ICloudStorageRequest
from renku_data_services.storage.models import CloudStorage
from renku_data_services.storage.rclone import RCloneValidator

_sanitize_for_serialization = client.ApiClient().sanitize_for_serialization


class RCloneStorageRequest(Schema):
    """Request for RClone based storage."""

    class Meta:
        """Configuration."""

        unknown = EXCLUDE

    source_path = fields.Str()
    target_path = fields.Str()
    configuration = fields.Dict(keys=fields.Str(), values=fields.Raw(), load_default=None, allow_none=True)
    storage_id = fields.Str(load_default=None, allow_none=True)
    readonly = fields.Bool(load_default=True, allow_none=False)

    @validates_schema
    def validate_storage(self, data: dict, **kwargs: dict) -> None:
        """Validate a storage request."""
        if data.get("storage_id") and (data.get("source_path") or data.get("target_path")):
            raise ValidationError("'storage_id' cannot be used together with 'source_path' or 'target_path'")


class RCloneStorageRequestOverride(Protocol):
    """A small dataclass for handling overrides to the data connector requests."""

    source_path: str | None = None
    target_path: str | None = None
    configuration: dict[str, Any] | None = None
    readonly: bool | None = None


class RCloneStorage(ICloudStorageRequest):
    """RClone based storage."""

    pvc_secret_annotation_name: Final[str] = "csi-rclone.dev/secretName"

    def __init__(
        self,
        source_path: str,
        configuration: dict[str, Any],
        readonly: bool,
        mount_folder: str,
        name: Optional[str],
        secrets: dict[str, str],  # "Mapping between secret ID (key) and secret name (value)
        storage_class: str,
        user_secret_key: str | None = None,
    ) -> None:
        """Creates a cloud storage instance without validating the configuration."""
        self.configuration = configuration
        self.source_path = source_path
        self.mount_folder = mount_folder
        self.readonly = readonly
        self.name = name
        self.secrets = secrets
        self.base_name: str | None = None
        self.user_secret_key = user_secret_key
        self.storage_class = storage_class
        validator = RCloneValidator()
        validator.inject_default_values(self.configuration)

    @classmethod
    async def storage_from_schema(
        cls,
        data: dict[str, Any],
        work_dir: PurePosixPath,
        saved_storage: CloudStorage | None,
        storage_class: str,
        user_secret_key: str | None = None,
    ) -> Self:
        """Create storage object from request."""
        name = None
        if saved_storage:
            configuration = {**saved_storage.configuration.model_dump(), **(data.get("configuration", {}))}
            readonly = saved_storage.readonly
            name = saved_storage.name
        else:
            source_path = data["source_path"]
            target_path = data["target_path"]
            configuration = data["configuration"]
            readonly = data.get("readonly", True)

        # NOTE: This is used only in Renku v1, there we do not save secrets for storage
        secrets: dict[str, str] = {}
        mount_folder = str(work_dir / target_path)
        return cls(
            source_path=source_path,
            configuration=configuration,
            readonly=readonly,
            mount_folder=mount_folder,
            name=name,
            storage_class=storage_class,
            secrets=secrets,
            user_secret_key=user_secret_key,
        )

    def pvc(
        self,
        base_name: str,
        namespace: str,
        labels: dict[str, str] | None = None,
        annotations: dict[str, str] | None = None,
    ) -> client.V1PersistentVolumeClaim:
        """The PVC for mounting cloud storage."""
        return client.V1PersistentVolumeClaim(
            api_version="v1",
            kind="PersistentVolumeClaim",
            metadata=client.V1ObjectMeta(
                name=base_name,
                namespace=namespace,
                annotations={self.pvc_secret_annotation_name: base_name} | (annotations or {}),
                labels={"name": base_name} | (labels or {}),
            ),
            spec=client.V1PersistentVolumeClaimSpec(
                access_modes=["ReadOnlyMany" if self.readonly else "ReadWriteMany"],
                resources=client.V1VolumeResourceRequirements(requests={"storage": "10Gi"}),
                storage_class_name=self.storage_class,
            ),
        )

    def volume_mount(self, base_name: str) -> client.V1VolumeMount:
        """The volume mount for cloud storage."""
        return client.V1VolumeMount(
            mount_path=self.mount_folder,
            name=base_name,
            read_only=self.readonly,
        )

    def volume(self, base_name: str) -> client.V1Volume:
        """The volume entry for the statefulset specification."""
        return client.V1Volume(
            name=base_name,
            persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                claim_name=base_name, read_only=self.readonly
            ),
        )

    def secret(
        self,
        base_name: str,
        namespace: str,
        labels: dict[str, str] | None = None,
        annotations: dict[str, str] | None = None,
        user_secret_key: str | None = None,
    ) -> client.V1Secret:
        """The secret containing the configuration for the rclone csi driver."""
        string_data = {
            "remote": self.name or base_name,
            "remotePath": self.source_path,
            "configData": self.config_string(self.name or base_name),
        }
        string_data.update(self.mount_options())
        # NOTE: in Renku v1 this function is not directly called so the base name
        # comes from the user_secret_key property on the class instance
        if self.user_secret_key:
            string_data["secretKey"] = self.user_secret_key
        if user_secret_key:
            string_data["secretKey"] = user_secret_key
        return client.V1Secret(
            api_version="v1",
            kind="Secret",
            metadata=client.V1ObjectMeta(
                name=base_name,
                namespace=namespace,
                annotations=annotations,
                labels={"name": base_name} | (labels or {}),
            ),
            string_data=string_data,
        )

    def get_manifest_patch(
        self,
        base_name: str,
        namespace: str,
        labels: dict[str, str] | None = None,
        annotations: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Get server manifest patch."""
        self.base_name = base_name
        patches = []
        patches.append(
            {
                "type": "application/json-patch+json",
                "patch": [
                    {
                        "op": "add",
                        "path": f"/{base_name}-pv",
                        "value": _sanitize_for_serialization(self.pvc(base_name, namespace, labels, annotations)),
                    },
                    {
                        "op": "add",
                        "path": f"/{base_name}-secret",
                        "value": _sanitize_for_serialization(self.secret(base_name, namespace, labels, annotations)),
                    },
                    {
                        "op": "add",
                        "path": "/statefulset/spec/template/spec/containers/0/volumeMounts/-",
                        "value": _sanitize_for_serialization(self.volume_mount(base_name)),
                    },
                    {
                        "op": "add",
                        "path": "/statefulset/spec/template/spec/volumes/-",
                        "value": _sanitize_for_serialization(self.volume(base_name)),
                    },
                ],
            }
        )
        return patches

    def config_string(self, name: str) -> str:
        """Convert configuration object to string representation.

        Needed to create RClone compatible INI files.
        """
        if not self.configuration:
            raise ValidationError("Missing configuration for cloud storage")

        # TODO Use RCloneValidator.get_real_configuration(...) instead.
        # Transform configuration for polybox, switchDrive, openbis or sftp
        storage_type = self.configuration.get("type", "")
        access = self.configuration.get("provider", "")

        if storage_type == "polybox" or storage_type == "switchDrive":
            self.configuration["type"] = "webdav"
            self.configuration["provider"] = ""
            # NOTE: Without the vendor field mounting storage and editing files results in the modification
            # time for touched files to be temporarily set to `1999-09-04` which causes the text
            # editor to complain that the file has changed and whether it should overwrite new changes.
            self.configuration["vendor"] = "owncloud"
        elif storage_type == "s3" and access == "Switch":
            # Switch is a fake provider we add for users, we need to replace it since rclone itself
            # doesn't know it
            self.configuration["provider"] = "Other"
        elif storage_type == "openbis":
            self.configuration["type"] = "sftp"
            self.configuration["port"] = "2222"
            self.configuration["user"] = "?"
            self.configuration["pass"] = self.configuration.pop("session_token", None) or self.configuration["pass"]

        if storage_type == "sftp" or storage_type == "openbis":
            # Do not allow retries for sftp
            # Reference: https://rclone.org/docs/#globalconfig
            self.configuration["override.low_level_retries"] = 1

        if access == "shared" and storage_type == "polybox":
            self.configuration["url"] = "https://polybox.ethz.ch/public.php/webdav/"
        elif access == "shared" and storage_type == "switchDrive":
            self.configuration["url"] = "https://drive.switch.ch/public.php/webdav/"
        elif access == "personal" and storage_type == "polybox":
            self.configuration["url"] = "https://polybox.ethz.ch/remote.php/webdav/"
        elif access == "personal" and storage_type == "switchDrive":
            self.configuration["url"] = "https://drive.switch.ch/remote.php/webdav/"

        # Extract the user from the public link
        if access == "shared" and storage_type in {"polybox", "switchDrive"}:
            public_link = self.configuration.get("public_link", "")
            user_identifier = public_link.split("/")[-1]
            self.configuration["user"] = user_identifier

        parser = ConfigParser(interpolation=None)
        parser.add_section(name)

        def _stringify(value: Any) -> str:
            if isinstance(value, bool):
                return "true" if value else "false"
            return str(value)

        for k, v in self.configuration.items():
            parser.set(name, k, _stringify(v))
        stringio = StringIO()
        parser.write(stringio)
        return stringio.getvalue()

    def with_override(self, override: RCloneStorageRequestOverride) -> "RCloneStorage":
        """Override certain fields on the storage."""
        return RCloneStorage(
            source_path=override.source_path if override.source_path else self.source_path,
            mount_folder=override.target_path if override.target_path else self.mount_folder,
            readonly=override.readonly if override.readonly is not None else self.readonly,
            configuration=override.configuration if override.configuration else self.configuration,
            name=self.name,
            secrets=self.secrets,
            storage_class=self.storage_class,
            user_secret_key=self.user_secret_key,
        )

    def mount_options(self) -> dict[str, str]:
        """Returns extra mount options for this storage."""
        if not self.configuration:
            raise ValidationError("Missing configuration for cloud storage")

        vfs_options: dict[str, Any] = dict()
        mount_options: dict[str, Any] = dict()
        storage_type = self.configuration.get("type", "")
        if storage_type == "doi":
            vfs_options["CacheMode"] = "full"
            mount_options["AttrTimeout"] = "41s"

        options: dict[str, str] = dict()
        if vfs_options:
            options["vfsOpt"] = json.dumps(vfs_options)
        if mount_options:
            options["mountOpt"] = json.dumps(mount_options)
        return options

    def __repr__(self) -> str:
        """Override to make sure no secrets or sensitive configuration gets printed in logs."""
        return (
            f"{RCloneStorageRequest.__name__}(name={self.name}, source_path={self.source_path}, "
            f"mount_folder={self.mount_folder}, readonly={self.readonly})"
        )
