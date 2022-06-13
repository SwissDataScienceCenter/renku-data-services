from marshmallow import fields, pre_dump, Schema


class AutosavesItem(Schema):
    """Information about an autosave item."""

    commit = fields.String(required=True)
    branch = fields.String(required=True)
    pvs = fields.Bool(required=True)
    date = fields.DateTime(required=True)
    name = fields.String(required=True)

    @pre_dump
    def extract_data(self, autosave, *args, **kwargs):
        return {
            "branch": autosave.root_branch_name,
            "commit": autosave.root_commit_sha,
            "pvs": False,
            "date": autosave.creation_date,
            "name": autosave.name,
        }


class AutosavesList(Schema):
    """List of autosaves branches or PVs."""

    pvsSupport = fields.Bool(required=True)
    autosaves = fields.List(fields.Nested(AutosavesItem), load_default=[])
