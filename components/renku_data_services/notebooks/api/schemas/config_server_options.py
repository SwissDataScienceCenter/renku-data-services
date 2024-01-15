from marshmallow import EXCLUDE, Schema, fields, validate


class BaseServerOptionsChoice(Schema):
    order = fields.Int(required=True, validate=lambda x: x >= 1)
    displayName = fields.Str(required=True)
    type = fields.Str(required=True, validate=validate.OneOf(["enum", "boolean"]))


class StringServerOptionsChoice(BaseServerOptionsChoice):
    default = fields.Str(required=True)
    options = fields.List(fields.Str(required=True))


class BoolServerOptionsChoice(BaseServerOptionsChoice):
    default = fields.Bool(required=True)


class ServerOptionsChoices(Schema):
    """Used to deserialize (load) the server options choices from the Helm values file."""

    class Meta:
        unknown = EXCLUDE

    defaultUrl = fields.Nested(StringServerOptionsChoice, required=False)
    lfs_auto_fetch = fields.Nested(BoolServerOptionsChoice, required=False)


class ServerOptionsDefaults(Schema):
    """Used to deserialize (load) the server options defaults from the Helm values file."""

    class Meta:
        unknown = EXCLUDE

    defaultUrl = fields.Str(required=True)
    lfs_auto_fetch = fields.Bool(required=True)


class ServerOptionsEndpointResponse(ServerOptionsChoices):
    """Used to serialize the server options sent out through the server_options endpoint."""

    cloudstorage = fields.Nested(
        Schema.from_dict({"enabled": fields.Bool(required=True)})(),
        required=True,
    )
