"""Version endpoint schema."""

from marshmallow import Schema, fields


class CullingThreshold(Schema):
    """Culling thresholds info."""

    idle = fields.Int(required=True)
    hibernation = fields.Int(required=True)


class DefaultCullingThresholds(Schema):
    """Culling thresholds for this deployment."""

    registered = fields.Nested(CullingThreshold, required=True)
    anonymous = fields.Nested(CullingThreshold, required=True)


class NotebooksServiceInfo(Schema):
    """Various notebooks service info."""

    anonymousSessionsEnabled = fields.Boolean(required=True)
    cloudstorageEnabled = fields.Boolean(required=True)
    sshEnabled = fields.Boolean(required=True)
    defaultCullingThresholds = fields.Nested(DefaultCullingThresholds, required=True)


class NotebooksServiceVersions(Schema):
    """Notebooks service version and info."""

    data = fields.Nested(NotebooksServiceInfo, required=True)
    version = fields.String(required=True)


class VersionResponse(Schema):
    """The response for /version endpoint."""

    name = fields.String(required=True)
    versions = fields.List(fields.Nested(NotebooksServiceVersions), required=True)
