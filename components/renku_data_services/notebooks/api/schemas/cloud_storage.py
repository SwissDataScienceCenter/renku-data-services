"""Schema for cloudstorage config."""

import json
from configparser import ConfigParser
from io import StringIO
from typing import Any, Final, Protocol

from kubernetes import client
from marshmallow import EXCLUDE, Schema, ValidationError, fields, validates_schema

from renku_data_services.errors import errors
from renku_data_services.k8s.models import sanitizer
from renku_data_services.notebooks.api.classes.cloud_storage import ICloudStorageRequest
from renku_data_services.storage.rclone import convert_rclone_configuration, get_rclone_validator


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
    """RClone based storage.

    Note at initialization time this class converts the RClone configuration to pure
    RClone configuration, it removes and converts all renku-specific providers and properties.
    """

    pvc_secret_annotation_name: Final[str] = "csi-rclone.dev/secretName"

    def __init__(
        self,
        source_path: str,
        configuration: dict[str, Any],
        readonly: bool,
        mount_folder: str,
        name: str | None,
        secrets: dict[str, str],  # "Mapping between secret ID (key) and secret name (value)
        storage_class: str,
        user_secret_key: str | None = None,
    ) -> None:
        """Creates a cloud storage instance without validating the configuration."""
        self.source_path = source_path
        self.mount_folder = mount_folder
        self.readonly = readonly
        self.name = name
        self.secrets = secrets
        self.base_name: str | None = None
        self.user_secret_key = user_secret_key
        self.storage_class = storage_class
        validator = get_rclone_validator()
        configuration = validator.inject_default_values(configuration)
        configuration = convert_rclone_configuration(configuration)
        self.configuration = configuration

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
        # A Rclone config that contains multiple remotes will be of shape dict[str, dict[str, Any]]
        # A regular Rclone config with a single remote will be like dict[str, Any]
        multiple_remotes = all([isinstance(i, dict) for i in self.configuration.values()])
        string_data = {
            "remote": self.name or base_name,
            "remotePath": self.source_path,
            "configData": self._config_string_multi_remote()
            if multiple_remotes
            else self._config_string_single_remote(self.name or base_name),
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
                        "value": sanitizer(self.pvc(base_name, namespace, labels, annotations)),
                    },
                    {
                        "op": "add",
                        "path": f"/{base_name}-secret",
                        "value": sanitizer(self.secret(base_name, namespace, labels, annotations)),
                    },
                    {
                        "op": "add",
                        "path": "/statefulset/spec/template/spec/containers/0/volumeMounts/-",
                        "value": sanitizer(self.volume_mount(base_name)),
                    },
                    {
                        "op": "add",
                        "path": "/statefulset/spec/template/spec/volumes/-",
                        "value": sanitizer(self.volume(base_name)),
                    },
                ],
            }
        )
        return patches

    @staticmethod
    def _stringify_bool(value: Any) -> str:
        """Converts booleans to a rclone compliant values."""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def _config_string_multi_remote(self) -> str:
        """Convert configuration object to string representation.

        Used when the configuration contains multiple remotes.
        Expects the dictionary to be like configuration[remote][remote_property] = "value"
        So an rclone config that should turn out like this:
            [remote1]
            type = s3
            endpoint = https://os.zhdk.cloud.switch.ch
            provider = Other

            [remote2]
            type = s3
            provider = AWS
        Will be in a configuration like this:
        {
            "remote1": {"type": "s3", "endpoint": "https://os.zhdk.cloud.switch.ch", "provider": "Other"},
            "remote2": {"type": "s3", "provider": "AWS"},
        }
        Needed to create RClone compatible INI files.
        """
        if not self.configuration:
            raise ValidationError("Missing configuration for cloud storage")

        # Validate that the structure makes sense
        if not all([isinstance(i, dict) for i in self.configuration.values()]):
            raise errors.ValidationError(
                message="The rclone configuration that contains multiple remotes was expected but the format "
                "looks like a single remote."
            )

        parser = ConfigParser(interpolation=None)

        for section_name, section in self.configuration.items():
            parser.add_section(section_name)
            for k, v in section.items():
                parser.set(section_name, k, self._stringify_bool(v))

        stringio = StringIO()
        parser.write(stringio)
        return stringio.getvalue()

    def _config_string_single_remote(self, name: str) -> str:
        """Convert configuration object to string representation.

        A single remote configuration looks like this: {"type": "s3", "provider": "AWS"},
        If the name is "remote1" then it is converted to a configuration like this:
            [remote1]
            type = s3
            provider = AWS
        Needed to create RClone compatible INI files.
        """
        if not self.configuration:
            raise ValidationError("Missing configuration for cloud storage")

        parser = ConfigParser(interpolation=None)
        parser.add_section(name)

        for k, v in self.configuration.items():
            parser.set(name, k, self._stringify_bool(v))
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
