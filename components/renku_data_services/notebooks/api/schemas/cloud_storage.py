from marshmallow import fields, EXCLUDE, validate, ValidationError, Schema, post_load

from ..classes.s3mount import S3mount


class LaunchNotebookRequestS3mount(Schema):
    class Meta:
        unknown = EXCLUDE

    access_key = fields.Str(required=False, load_default=None)
    secret_key = fields.Str(required=False, load_default=None)
    endpoint = fields.Url(
        required=True, schemes=["http", "https"], relative=False, require_tld=True
    )
    bucket = fields.Str(required=True, validate=validate.Length(min=1))

    @post_load
    def create_s3mount_object(self, data, **kwargs):
        if data["access_key"] == "":
            data.pop("access_key")
        if data["secret_key"] == "":
            data.pop("secret_key")
        s3mount = S3mount(**data, mount_folder="/cloudstorage", read_only=True)
        if not s3mount.bucket_exists:
            raise ValidationError(
                f"Cannot find bucket {s3mount.bucket} at endpoint {s3mount.endpoint}. "
                "Please make sure you have provided the correct "
                "credentials, bucket name and endpoint."
            )
        return s3mount


class LaunchNotebookResponseS3mount(LaunchNotebookRequestS3mount):
    class Meta:
        fields = ("endpoint", "bucket")
