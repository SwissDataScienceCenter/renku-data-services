"""Schema for server logs."""

from marshmallow import INCLUDE, Schema, fields, post_dump

_ServerLogs = Schema.from_dict({"jupyter-server": fields.String(required=False)})


class ServerLogs(_ServerLogs):
    """Server logs schema."""

    class Meta:
        unknown = INCLUDE  # only affects loading, not dumping

    @post_dump(pass_original=True)
    def keep_unknowns(self, output, orig, **kwargs):
        """Keep unknowns when dumping."""
        output = {**orig, **output}
        return output
