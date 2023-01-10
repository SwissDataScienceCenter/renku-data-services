from marshmallow import EXCLUDE, Schema, ValidationError, fields, post_load, validate

from ..classes.cloud_storage.s3mount import S3Request
from ..classes.cloud_storage.azure_blob import AzureBlobRequest
from ...config import config


class LaunchNotebookRequestCloudStorage(Schema):
    class Meta:
        unknown = EXCLUDE

    access_key = fields.Str(required=False, load_default=None)
    secret_key = fields.Str(required=False, load_default=None)
    endpoint = fields.Url(
        required=True, schemes=["http", "https"], relative=False, require_tld=True
    )
    bucket = fields.Str(required=True, validate=validate.Length(min=1))

    @post_load
    def create_cloud_storage_object(self, data, **kwargs):
        if data["access_key"] == "":
            data.pop("access_key")
        if data["secret_key"] == "":
            data.pop("secret_key")

        if (
            data.get("access_key") is None
            and data.get("secret_key") is not None
            and config.cloud_storage.azure_blob.enabled
        ):
            cloud_storage = AzureBlobRequest(
                endpoint=data["endpoint"],
                container=data["bucket"],
                credential=data["secret_key"],
                mount_folder=config.cloud_storage.mount_folder,
                read_only=config.cloud_storage.azure_blob.read_only,
            )
        elif config.cloud_storage.s3.enabled:
            cloud_storage = S3Request(
                endpoint=data["endpoint"],
                bucket=data["bucket"],
                access_key=data.get("access_key"),
                secret_key=data.get("secret_key"),
                mount_folder=config.cloud_storage.mount_folder,
                read_only=config.cloud_storage.s3.read_only,
            )
        else:
            raise ValidationError(
                "Cannot accept the provided cloud storage parameters because "
                "the requested storage type has not been properly setup or enabled."
            )

        if not cloud_storage.exists:
            raise ValidationError(
                f"Cannot find bucket {data['bucket']} at endpoint {data['endpoint']}. "
                "Please make sure you have provided the correct "
                "credentials, bucket name and endpoint."
            )
        return cloud_storage


class LaunchNotebookResponseCloudStorage(LaunchNotebookRequestCloudStorage):
    class Meta:
        fields = ("endpoint", "bucket")
