from marshmallow import Schema, fields

from .custom_fields import LowercaseString


class Repository(Schema):
    """Information required to clone a repository."""

    # namespaces in gitlab are NOT case-sensitive
    namespace = LowercaseString(required=True)
    # project names in gitlab are NOT case-sensitive
    project = LowercaseString(required=True)
    # branch names in gitlab are case-sensitive
    branch = fields.Str(load_default="master")
    commit_sha = fields.Str(required=True)
