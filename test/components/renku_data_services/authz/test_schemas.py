from dataclasses import asdict, dataclass, field
from pathlib import Path
from subprocess import check_call

import pytest
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString

from renku_data_services.authz import schemas


@dataclass
class SpiceDBSchema:
    schema: str
    relationships: list[str] = field(default_factory=list)
    assertions: dict[str, list[str]] = field(default_factory=dict)
    validation: dict[str, list[str]] = field(default_factory=dict)

    def to_yaml(self, path: Path):
        output = asdict(self)
        if output["relationships"]:
            output["relationships"] = LiteralScalarString("\n".join(self.relationships))
        else:
            del output["relationships"]
        output["schema"] = LiteralScalarString(self.schema)
        YAML().dump(output, path)


@pytest.fixture
def v1_schema() -> SpiceDBSchema:
    return SpiceDBSchema(
        schemas.v1,
        relationships=[
            "platform:renku#admin@user:admin1",
            "platform:renku#admin@user:admin2",
            "project:public1#owner@user:project_public1_owner",
            "project:public1#viewer@user:*",
            "project:public1#viewer@anonymous_user:*",
            "project:private1#owner@user:project_private1_owner",
            "project:private1#viewer@user:project_private1_reader",
            "project:private1#editor@user:project_private1_editor",
            "project:private1#project_platform@platform:renku",
            "project:public1#project_platform@platform:renku",
        ],
        assertions={
            "assertTrue": [
                "project:private1#read@user:project_private1_reader",
                "project:private1#write@user:project_private1_editor",
                "project:private1#read@user:project_private1_owner",
                "project:private1#write@user:project_private1_owner",
                "project:private1#delete@user:project_private1_owner",
                "project:private1#change_membership@user:project_private1_owner",
                "project:public1#read@user:project_private1_reader",
                "project:public1#read@user:random",
                "project:public1#read@user:admin1",
                "project:public1#write@user:admin1",
                "project:public1#delete@user:admin1",
                "project:public1#change_membership@user:admin1",
                "project:public1#read@anonymous_user:any",
                "project:private1#read@user:admin1",
                "project:private1#write@user:admin1",
                "project:private1#delete@user:admin1",
                "project:private1#read@user:admin2",
                "project:private1#write@user:admin2",
                "project:private1#delete@user:admin2",
                "project:private1#change_membership@user:admin2",
            ],
            "assertFalse": [
                "project:private1#read@user:random",
                "project:private1#write@user:random",
                "project:private1#delete@user:random",
                "project:public1#write@user:random",
                "project:public1#delete@user:random",
                "project:public1#write@user:project_private1_reader",
                "project:public1#delete@user:project_private1_reader",
                "project:public1#change_membership@user:project_private1_reader",
                "project:private1#write@user:project_private1_reader",
                "project:private1#delete@user:project_private1_reader",
                "project:private1#change_membership@user:project_private1_reader",
                "project:public1#write@user:project_private1_owner",
                "project:public1#delete@user:project_private1_owner",
                "project:private1#read@user:project_public1_owner",
                "project:private1#write@user:project_public1_owner",
                "project:private1#delete@user:project_public1_owner",
                "project:private1#change_membership@user:project_public1_owner",
            ],
        },
        validation={
            "project:private1#write": [
                "[user:admin1] is <platform:renku#admin>",
                "[user:admin2] is <platform:renku#admin>",
                "[user:project_private1_editor] is <project:private1#editor>",
                "[user:project_private1_owner] is <project:private1#owner>",
            ],
            "project:private1#delete": [
                "[user:admin1] is <platform:renku#admin>",
                "[user:admin2] is <platform:renku#admin>",
                "[user:project_private1_owner] is <project:private1#owner>",
            ],
            "project:private1#change_membership": [
                "[user:admin1] is <platform:renku#admin>",
                "[user:admin2] is <platform:renku#admin>",
                "[user:project_private1_owner] is <project:private1#owner>",
            ],
            "project:private1#read": [
                "[user:admin1] is <platform:renku#admin>",
                "[user:admin2] is <platform:renku#admin>",
                "[user:project_private1_owner] is <project:private1#owner>",
                "[user:project_private1_reader] is <project:private1#viewer>",
                "[user:project_private1_editor] is <project:private1#editor>",
            ],
            "project:public1#write": [
                "[user:admin1] is <platform:renku#admin>",
                "[user:admin2] is <platform:renku#admin>",
                "[user:project_public1_owner] is <project:public1#owner>",
            ],
            "project:public1#delete": [
                "[user:admin1] is <platform:renku#admin>",
                "[user:admin2] is <platform:renku#admin>",
                "[user:project_public1_owner] is <project:public1#owner>",
            ],
            "project:public1#change_membership": [
                "[user:admin1] is <platform:renku#admin>",
                "[user:admin2] is <platform:renku#admin>",
                "[user:project_public1_owner] is <project:public1#owner>",
            ],
            "project:public1#read": [
                "[anonymous_user:*] is <project:public1#viewer>",
                "[user:*] is <project:public1#viewer>",
                "[user:admin1] is <platform:renku#admin>",
                "[user:admin2] is <platform:renku#admin>",
                "[user:project_public1_owner] is <project:public1#owner>",
            ],
        },
    )


def test_schema(tmp_path: Path, v1_schema: SpiceDBSchema):
    validation_file = tmp_path / "validate.yaml"
    v1_schema.to_yaml(validation_file)
    check_call(["zed", "validate", validation_file.as_uri()])
