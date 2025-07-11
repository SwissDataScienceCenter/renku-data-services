"""Server POST schemas."""

from marshmallow import Schema, fields

from .cloud_storage import RCloneStorageRequest
from .custom_fields import LowercaseString
from .repository import Repository
from .secrets import UserSecrets
from .server_options import LaunchNotebookRequestServerOptions


class LaunchNotebookRequestWithoutStorageBase(Schema):
    """Base class used to validate the requesting for launching a jupyter server."""

    notebook = fields.Str(load_default=None)
    # the server options field is honored only if provided
    # it will be matched against the closest resource class
    server_options = fields.Nested(
        LaunchNotebookRequestServerOptions(),
        data_key="serverOptions",
        required=False,
    )
    resource_class_id = fields.Int(required=False, load_default=None)
    # storage is in gigabytes
    storage = fields.Int(
        required=False,
        load_default=1,
    )
    lfs_auto_fetch = fields.Bool(required=False, load_default=False)
    default_url = fields.Str(
        required=False,
        load_default="/lab",
    )
    environment_variables = fields.Dict(keys=fields.Str(), values=fields.Str(), load_default=dict())
    # User uploaded secrets
    # Contains secret id list and mount path
    user_secrets = fields.Nested(UserSecrets(), required=False, load_default=None)
    cluster_name = fields.Str(required=False, load_default=None)


class LaunchNotebookRequestWithoutStorage(LaunchNotebookRequestWithoutStorageBase):
    """Used to validate the requesting for launching a jupyter server."""

    # namespaces in gitlab are NOT case-sensitive
    namespace = LowercaseString(required=True)
    # project names in gitlab are NOT case-sensitive
    project = LowercaseString(required=True)
    # branch names in gitlab are case-sensitive
    branch = fields.Str(load_default="master")
    commit_sha = fields.Str(required=True)
    image = fields.Str(load_default=None)


class LaunchNotebookRequestWithStorage(LaunchNotebookRequestWithoutStorage):
    """Used to validate the requesting for launching a jupyter server."""

    cloudstorage = fields.List(
        fields.Nested(RCloneStorageRequest()),
        required=False,
        load_default=[],
    )


LaunchNotebookRequest = LaunchNotebookRequestWithStorage


class Renku2LaunchNotebookRequest(LaunchNotebookRequestWithoutStorageBase):
    """To validate start request for Renku 2.0 sessions."""

    project_id = fields.String(required=True)
    launcher_id = fields.String(required=True)
    image = fields.Str(required=True)
    repositories = fields.List(fields.Nested(Repository()), required=False, load_default=[])

    # TODO: Make Renku2 a feature flag and add these fields to a specific Renku2 class
    cloudstorage = fields.List(
        fields.Nested(RCloneStorageRequest()),
        required=False,
        load_default=[],
    )
