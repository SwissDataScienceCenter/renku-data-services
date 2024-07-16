"""Schema for a git repository."""

from marshmallow import Schema, String, fields


class Repository(Schema):
    """Information required to clone a repository."""

    url: String = fields.Str(required=True)
    dirname: String | None = fields.Str()
    branch: String | None = fields.Str()
    commit_sha: String | None = fields.Str()
