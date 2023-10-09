from pathlib import Path
from typing import Any, Dict, Optional

from marshmallow import EXCLUDE, Schema, ValidationError, fields, validates_schema

from ...config import config
from ..classes.cloud_storage.azure_blob import AzureBlobRequest
from ..classes.cloud_storage.s3mount import S3Request
from ..classes.user import User


class RCloneStorageRequest(Schema):
    class Meta:
        unknown = EXCLUDE

    source_path: Optional[str] = fields.Str()
    target_path: Optional[str] = fields.Str()
    configuration: Optional[Dict[str, Any]] = fields.Dict(
        keys=fields.Str(), values=fields.Raw(), load_default=None, allow_none=True
    )
    storage_id: Optional[str] = fields.Str(load_default=None, allow_none=True)
    readonly: bool = fields.Bool(load_default=True, allow_none=False)

    @validates_schema
    def validate_storage(self, data, **kwargs):
        if data.get("storage_id") and (data.get("source_path") or data.get("target_path")):
            raise ValidationError(
                "'storage_id' cannot be used together with 'source_path' or 'target_path'"
            )


def create_cloud_storage_object(data: Dict[str, Any], user: User, project_id: int, work_dir: Path):
    if data.get("storage_id") and (data.get("source_path") or data.get("target_path")):
        raise ValidationError(
            "'storage_id' cannot be used together with 'source_path' or 'target_path'"
        )
    if data.get("storage_id"):
        # Load from storage service
        if user.access_token is None:
            raise ValidationError("Storage mounting only supported for logged-in users.")
        if project_id < 1:
            raise ValidationError("Could not get gitlab project id")
        (
            configuration,
            source_path,
            target_path,
            readonly,
        ) = config.storage_validator.get_storage_by_id(user, project_id, data["storage_id"])
        configuration = {**configuration, **(data.get("configuration") or {})}
        readonly = data.get("readonly", readonly)
    else:
        source_path = data["source_path"]
        target_path = data["target_path"]
        configuration = data["configuration"]
        readonly = data.get("readonly", True)

    config.storage_validator.validate_storage_configuration(configuration)

    path = source_path.lstrip("/")
    if "/" in path:
        bucket, source_path = path.split("/", 1)
    else:
        bucket, source_path = path, ""

    cloud_storage: AzureBlobRequest | S3Request
    if (
        configuration.get("type") == "azureblob"
        and configuration.get("access_key_id") is None
        and configuration.get("secret_access_key") is not None
        and config.cloud_storage.azure_blob.enabled
    ):
        cloud_storage = AzureBlobRequest(
            endpoint=configuration["endpoint"],
            container=bucket,
            credential=configuration["secret_access_key"],
            mount_folder=work_dir / target_path,
            source_folder=source_path,
            read_only=readonly,
        )
    elif configuration.get("type") == "s3" and config.cloud_storage.s3.enabled:
        cloud_storage = S3Request(
            endpoint=configuration.get("endpoint"),
            region=configuration.get("region"),
            bucket=bucket,
            access_key=configuration.get("access_key_id"),
            secret_key=configuration.get("secret_access_key"),
            mount_folder=work_dir / target_path,
            source_folder=source_path,
            read_only=data.get("readonly", True),
        )
    else:
        raise ValidationError(
            "Cannot accept the provided cloud storage parameters because "
            "the requested storage type has not been properly setup or enabled."
        )

    if not cloud_storage.exists:
        raise ValidationError(
            f"Cannot find bucket {bucket} at endpoint {cloud_storage.endpoint}. "
            "Please make sure you have provided the correct "
            "credentials, bucket name and endpoint."
        )
    return cloud_storage


class LaunchNotebookResponseCloudStorage(RCloneStorageRequest):
    class Meta:
        fields = ("endpoint", "bucket", "mount_folder")
