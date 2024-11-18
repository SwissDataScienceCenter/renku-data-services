"""Schema for cloudstorage config."""

from configparser import ConfigParser
from io import StringIO
from pathlib import PurePosixPath
from typing import Any, Final, Optional, Protocol, Self

from kubernetes import client
from marshmallow import EXCLUDE, Schema, ValidationError, fields, validates_schema

from renku_data_services.base_models import APIUser
from renku_data_services.notebooks.api.classes.cloud_storage import ICloudStorageRequest
from renku_data_services.notebooks.config import NotebooksConfig

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
        config: NotebooksConfig,
    ) -> None:
        """Creates a cloud storage instance without validating the configuration."""
        self.config = config
        self.configuration = configuration
        self.source_path = source_path
        self.mount_folder = mount_folder
        self.readonly = readonly
        self.name = name

    @classmethod
    async def storage_from_schema(
        cls,
        data: dict[str, Any],
        user: APIUser,
        internal_gitlab_user: APIUser,
        project_id: int,
        work_dir: PurePosixPath,
        config: NotebooksConfig,
    ) -> Self:
        """Create storage object from request."""
        name = None
        if data.get("storage_id"):
            # Load from storage service
            if user.access_token is None:
                raise ValidationError("Storage mounting is only supported for logged-in users.")
            if project_id < 1:
                raise ValidationError("Could not get gitlab project id")
            (
                configuration,
                source_path,
                target_path,
                readonly,
                name,
            ) = await config.storage_validator.get_storage_by_id(
                user, internal_gitlab_user, project_id, data["storage_id"]
            )
            configuration = {**configuration, **(configuration or {})}
            readonly = readonly
        else:
            source_path = data["source_path"]
            target_path = data["target_path"]
            configuration = data["configuration"]
            readonly = data.get("readonly", True)
        mount_folder = str(work_dir / target_path)

        await config.storage_validator.validate_storage_configuration(configuration, source_path)
        return cls(source_path, configuration, readonly, mount_folder, name, config)

    def pvc(
        self,
        base_name: str,
        namespace: str,
        labels: dict[str, str] | None = None,
        annotations: dict[str, str] | None = None,
    ) -> client.V1PersistentVolumeClaim:
        """The PVC for mounting cloud storage."""
        return client.V1PersistentVolumeClaim(
            metadata=client.V1ObjectMeta(
                name=base_name,
                namespace=namespace,
                annotations={self.pvc_secret_annotation_name: base_name} | (annotations or {}),
                labels={"name": base_name} | (labels or {}),
            ),
            spec=client.V1PersistentVolumeClaimSpec(
                access_modes=["ReadOnlyMany" if self.readonly else "ReadWriteMany"],
                resources=client.V1VolumeResourceRequirements(requests={"storage": "10Gi"}),
                storage_class_name=self.config.cloud_storage.storage_class,
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
        if user_secret_key:
            string_data["secretKey"] = user_secret_key
        return client.V1Secret(
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
        """Convert configuration oblect to string representation.

        Needed to create RClone compatible INI files.
        """
        if not self.configuration:
            raise ValidationError("Missing configuration for cloud storage")

        # Transform configuration for polybox or switchDrive only if access_level is Public
        storage_type = self.configuration.get("storage_type", "").lower()
        access_level = self.configuration.get("access_level", "").lower()

        if storage_type == "polybox" or storage_type == "switchDrive":
            self.configuration["type"] = "webdav"

        if access_level == "Public" and storage_type == "polybox":
            self.configuration["url"] = "https://polybox.ethz.ch/public.php/webdav/"
        if access_level == "Public" and storage_type == "switchDrive":
            self.configuration["url"] = "https://drive.switch.ch/public.php/webdav/"

        # Extract the user from the public link
        if access_level == "Public" and storage_type in {"polybox", "switchDrive"}:
            public_link = self.configuration.get("public_link", "")
            user_identifier = public_link.split("/")[-1]
            self.configuration["user"] = user_identifier

        if self.configuration["type"] == "s3" and self.configuration.get("provider", None) == "Switch":
            # Switch is a fake provider we add for users, we need to replace it since rclone itself
            # doesn't know it
            self.configuration["provider"] = "Other"

        parser = ConfigParser()
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
            config=self.config,
        )


class LaunchNotebookResponseCloudStorage(RCloneStorageRequest):
    """Notebook launch response with cloud storage attached."""

    class Meta:
        """Specify fields."""

        fields = ("remote", "mount_folder", "type")
