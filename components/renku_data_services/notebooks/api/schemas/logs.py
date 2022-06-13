from marshmallow import Schema, INCLUDE, post_dump, fields


_ServerLogs = Schema.from_dict({"jupyter-server": fields.String(required=False)})


class ServerLogs(_ServerLogs):
    class Meta:
        unknown = INCLUDE  # only affects loading, not dumping

    @post_dump(pass_original=True)
    def keep_unknowns(self, output, orig, **kwargs):
        output = {**orig, **output}
        return output
