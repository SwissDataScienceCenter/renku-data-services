"""Schema for server logs."""

from marshmallow import INCLUDE, Schema, post_dump


class ServerLogs(Schema):
    """Server logs schema."""

    class Meta:
        """Custom configuration."""

        unknown = INCLUDE  # only affects loading, not dumping

    @post_dump(pass_original=True)
    def keep_unknowns(self, output: dict, orig: dict, **kwargs: dict) -> dict:
        """Keep unknowns when dumping."""
        output = {**orig, **output}
        return output
