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

    def to_yaml(self, path: Path) -> None:
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
        schemas._v1,
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


@pytest.fixture
def v2_schema() -> SpiceDBSchema:
    return SpiceDBSchema(
        schemas._v2,
        relationships=[
            "platform:renku#admin@user:admin1",
            "platform:renku#admin@user:admin2",
            "project:project1#owner@user:user1",
            "project:project1#project_namespace@user_namespace:user1",
            "project:project1#viewer@user:*",  # project1 is public
            "project:project1#viewer@anonymous_user:*",  # project1 is public
            "project:project1#project_platform@platform:renku",
            "project:project2#owner@user:user2",  # project 2 is private
            "project:project2#project_namespace@group:group1",
            "project:project2#viewer@user:project2_viewer",
            "project:project2#editor@user:project2_editor",
            "project:project2#project_platform@platform:renku",
            "group:group1#owner@user:user2",
            "group:group1#owner@user:group1_owner",
            "group:group1#editor@user:group1_editor",
            "group:group1#viewer@user:group1_viewer",
        ],
        assertions={
            "assertTrue": [
                # project1 owner can do everything
                "project:project1#read@user:user1",
                "project:project1#write@user:user1",
                "project:project1#change_membership@user:user1",
                "project:project1#delete@user:user1",
                # admins can do everything
                "project:project1#read@user:admin1",
                "project:project1#write@user:admin1",
                "project:project1#change_membership@user:admin1",
                "project:project1#delete@user:admin1",
                "project:project1#read@user:admin2",
                "project:project1#write@user:admin2",
                "project:project1#change_membership@user:admin2",
                "project:project1#delete@user:admin2",
                # project1 is public so everyone can read
                "project:project1#read@user:random_user",
                "project:project1#read@user:user2",
                "project:project1#read@anonymous_user:anon_user",
                # project2 is private, owner can do everything
                "project:project2#read@user:user2",
                "project:project2#write@user:user2",
                "project:project2#change_membership@user:user2",
                "project:project2#delete@user:user2",
                # project2 editor can act as project editor
                "project:project2#read@user:project2_editor",
                "project:project2#write@user:project2_editor",
                # project2 viewer can act as project viewer
                "project:project2#read@user:project2_viewer",
                # admins can do everything
                "project:project2#read@user:admin1",
                "project:project2#write@user:admin1",
                "project:project2#change_membership@user:admin1",
                "project:project2#delete@user:admin1",
                "project:project2#read@user:admin2",
                "project:project2#write@user:admin2",
                "project:project2#change_membership@user:admin2",
                "project:project2#delete@user:admin2",
                # group owner can act as project2 owner
                "project:project2#read@user:group1_owner",
                "project:project2#write@user:group1_owner",
                "project:project2#change_membership@user:group1_owner",
                "project:project2#delete@user:group1_owner",
                # group editor can act as project2 editor
                "project:project2#read@user:group1_editor",
                "project:project2#write@user:group1_editor",
                # group viewer can act as project2 viewer
                "project:project2#read@user:group1_viewer",
            ],
            "assertFalse": [
                # the owner of project2 cannot act like owner of project1
                "project:project1#write@user:user2",
                "project:project1#change_membership@user:user2",
                "project:project1#delete@user:user2",
                # the owner of project1 cannot act like owner of project2
                "project:project2#read@user:user1",
                "project:project2#write@user:user1",
                "project:project2#change_membership@user:user1",
                "project:project2#delete@user:user1",
                # anonymous or random users cannot do anything on private project like project2
                "project:project2#read@user:random",
                "project:project2#write@user:random",
                "project:project2#change_membership@user:random",
                "project:project2#delete@user:random",
                "project:project2#read@anonymous_user:random",
                "project:project2#write@anonymous_user:random",
                "project:project2#change_membership@anonymous_user:random",
                "project:project2#delete@anonymous_user:random",
                # anonymous or random users cannot do anything on private project like project2
                "project:project1#write@user:random",
                "project:project1#change_membership@user:random",
                "project:project1#delete@user:random",
                "project:project1#write@anonymous_user:random",
                "project:project1#change_membership@anonymous_user:random",
                "project:project1#delete@anonymous_user:random",
                # project2 editor cannot act like owner
                "project:project2#change_membership@user:project2_editor",
                "project:project2#delete@user:project2_editor",
                # project2 viewer cannot act like owner or editor
                "project:project2#write@user:project2_viewer",
                "project:project2#change_membership@user:project2_viewer",
                "project:project2#delete@user:project2_viewer",
            ],
        },
        validation={
            "project:project1#read": [
                "[user:admin1] is <platform:renku#admin>",
                "[user:admin2] is <platform:renku#admin>",
                "[user:user1] is <project:project1#owner>",
                # project1 is public so any user or any anonymous user can read
                "[user:*] is <project:project1#viewer>",
                "[anonymous_user:*] is <project:project1#viewer>",
            ],
            "project:project1#write": [
                "[user:admin1] is <platform:renku#admin>",
                "[user:admin2] is <platform:renku#admin>",
                "[user:user1] is <project:project1#owner>",
            ],
            "project:project1#delete": [
                "[user:admin1] is <platform:renku#admin>",
                "[user:admin2] is <platform:renku#admin>",
                "[user:user1] is <project:project1#owner>",
            ],
            "project:project1#change_membership": [
                "[user:admin1] is <platform:renku#admin>",
                "[user:admin2] is <platform:renku#admin>",
                "[user:user1] is <project:project1#owner>",
            ],
            "project:project2#read": [
                "[user:admin1] is <platform:renku#admin>",
                "[user:admin2] is <platform:renku#admin>",
                "[user:project2_editor] is <project:project2#editor>",
                "[user:project2_viewer] is <project:project2#viewer>",
                "[user:group1_owner] is <group:group1#owner>",
                "[user:group1_editor] is <group:group1#editor>",
                "[user:group1_viewer] is <group:group1#viewer>",
                "[user:user2] is <group:group1#owner>/<project:project2#owner>",
            ],
            "project:project2#write": [
                "[user:admin1] is <platform:renku#admin>",
                "[user:admin2] is <platform:renku#admin>",
                "[user:project2_editor] is <project:project2#editor>",
                "[user:group1_owner] is <group:group1#owner>",
                "[user:group1_editor] is <group:group1#editor>",
                "[user:user2] is <group:group1#owner>/<project:project2#owner>",
            ],
            "project:project2#delete": [
                "[user:admin1] is <platform:renku#admin>",
                "[user:admin2] is <platform:renku#admin>",
                "[user:group1_owner] is <group:group1#owner>",
                "[user:user2] is <group:group1#owner>/<project:project2#owner>",
            ],
            "project:project2#change_membership": [
                "[user:admin1] is <platform:renku#admin>",
                "[user:admin2] is <platform:renku#admin>",
                "[user:group1_owner] is <group:group1#owner>",
                "[user:user2] is <group:group1#owner>/<project:project2#owner>",
            ],
        },
    )


@pytest.fixture
def v5_schema() -> SpiceDBSchema:
    return SpiceDBSchema(
        schemas._v5,
        relationships=[
            "project:p1#owner@user:u1",
            "project:p1#public_viewer@user:*",
            "project:p1#public_viewer@anonymous_user:*",
            "project:p2#owner@user:u1",
            "project:p3#editor@user:u2",
            "project:p4#project_namespace@group:g1",
            "group:g1#editor@user:u1",
            "project:p5#viewer@user:u3",
            "project:p6#owner@user:u4",
            "project:p6#public_viewer@user:*",
            "project:p6#public_viewer@anonymous_user:*",
        ],
        assertions={
            "assertTrue": [
                "project:p2#non_public_read@user:u1",
                "project:p3#non_public_read@user:u2",
                "project:p4#non_public_read@user:u1",
                "project:p5#non_public_read@user:u3",
            ],
            "assertFalse": [
                "project:p1#non_public_read@user:u1",
                "project:p1#non_public_read@user:u2",
                "project:p1#non_public_read@user:u3",
                "project:p2#non_public_read@user:u2",
                "project:p2#non_public_read@user:u3",
                "project:p3#non_public_read@user:u1",
                "project:p3#non_public_read@user:u3",
                "project:p4#non_public_read@user:u2",
                "project:p4#non_public_read@user:u3",
                "project:p5#non_public_read@user:u1",
                "project:p5#non_public_read@user:u2",
                "project:p6#non_public_read@user:u4",
            ],
        },
        validation={},
    )


def test_v1_schema(tmp_path: Path, v1_schema: SpiceDBSchema) -> None:
    validation_file = tmp_path / "validate.yaml"
    v1_schema.to_yaml(validation_file)
    check_call(["zed", "validate", validation_file.as_uri()])


def test_v2_schema(tmp_path: Path, v2_schema: SpiceDBSchema) -> None:
    validation_file = tmp_path / "validate.yaml"
    v2_schema.to_yaml(validation_file)
    check_call(["zed", "validate", validation_file.as_uri()])


def test_v5_schema(tmp_path: Path, v5_schema: SpiceDBSchema) -> None:
    validation_file = tmp_path / "validate.yaml"
    v5_schema.to_yaml(validation_file)
    check_call(["zed", "validate", validation_file.as_uri()])
