"""Schema for a git repository."""

from marshmallow import Schema, fields


class Repository(Schema):
    """Information required to clone a repository."""

    url: str = fields.Str(required=True)
    dirname: str | None = fields.Str()
    branch: str | None = fields.Str()
    commit_sha: str | None = fields.Str()
