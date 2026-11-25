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


@pytest.fixture
def v6_schema() -> SpiceDBSchema:
    return SpiceDBSchema(
        schemas._v6,
        relationships=[
            # there is an an admin
            "platform:renku#admin@user:admin1",
            # user namespaces
            "user_namespace:user1#owner@user:user1",
            "user_namespace:user2#owner@user:user2",
            # project1 is public and owned by user1
            "project:project1#owner@user:user1",
            "project:project1#project_namespace@user_namespace:user1",
            "project:project1#public_viewer@user:*",
            "project:project1#public_viewer@anonymous_user:*",
            "project:project1#project_platform@platform:renku",
            # project2 is private, in group1 which is also private
            "project:project2#owner@user:user2",
            "project:project2#project_namespace@group:group1",
            # project2 has other generic members
            "project:project2#viewer@user:project2_viewer",
            "project:project2#editor@user:project2_editor",
            "project:project2#project_platform@platform:renku",
            # user2 is owner of group1
            "group:group1#owner@user:user2",
            # group1 has other generic members
            "group:group1#owner@user:group1_owner",
            "group:group1#editor@user:group1_editor",
            "group:group1#viewer@user:group1_viewer",
            # dc1 is owned by project1
            "data_connector:dc1#data_connector_namespace@project:project1",
            "data_connector:dc1#data_connector_platform@platform:renku",
            # dc2 is owned by group1
            "data_connector:dc2#data_connector_namespace@group:group1",
            "data_connector:dc2#data_connector_platform@platform:renku",
            # dc3 is owned by user1 and is private
            "data_connector:dc3#data_connector_namespace@user_namespace:user1",
            "data_connector:dc3#data_connector_platform@platform:renku",
            # dc4 is owned by user1 and is public
            "data_connector:dc4#data_connector_namespace@user_namespace:user1",
            "data_connector:dc4#data_connector_platform@platform:renku",
            "data_connector:dc4#public_viewer@user:*",
            "data_connector:dc4#public_viewer@anonymous_user:*",
        ],
        assertions={
            "assertTrue": [
                # admins can do everything to all data connectors
                "data_connector:dc1#delete@user:admin1",
                "data_connector:dc2#delete@user:admin1",
                "data_connector:dc3#delete@user:admin1",
                "data_connector:dc4#delete@user:admin1",
                "data_connector:dc1#write@user:admin1",
                "data_connector:dc2#write@user:admin1",
                "data_connector:dc3#write@user:admin1",
                "data_connector:dc4#write@user:admin1",
                "data_connector:dc1#read@user:admin1",
                "data_connector:dc2#read@user:admin1",
                "data_connector:dc3#read@user:admin1",
                "data_connector:dc4#read@user:admin1",
                # user1 can do everything on dc1 since it is owned by the project that user1 owns
                "data_connector:dc1#delete@user:user1",
                "data_connector:dc1#write@user:user1",
                "data_connector:dc1#read@user:user1",
                # user1 can read dc3 because it is owned by user1
                "data_connector:dc3#delete@user:user1",
                "data_connector:dc3#write@user:user1",
                "data_connector:dc3#read@user:user1",
                # user1 can read dc4 because it is owned by user1
                "data_connector:dc4#delete@user:user1",
                "data_connector:dc4#write@user:user1",
                "data_connector:dc4#read@user:user1",
                # user2 has full access on dc2 because they own the group that owns the dc
                "data_connector:dc2#delete@user:user2",
                "data_connector:dc2#write@user:user2",
                "data_connector:dc2#read@user:user2",
                # user2 has read access on dc4 because the dc is public
                "data_connector:dc4#read@user:user2",
                # anonymous user checks
                "data_connector:dc4#read@user:ANON",
                "data_connector:dc4#read@anonymous_user:ANON",
            ],
            "assertFalse": [
                # user1 has no access to dc2 since the dc is owned by group1 which is private
                # and user1 has no affiliation with group1
                "data_connector:dc2#delete@user:user1",
                "data_connector:dc2#write@user:user1",
                "data_connector:dc2#read@user:user1",
                # user2 has no access to dc1 because the dc is not public
                # and user2 has no access to the project that owns the dc
                "data_connector:dc1#read@user:user2",
                # user2 has no edit or write access to dc1
                "data_connector:dc1#delete@user:user2",
                "data_connector:dc1#write@user:user2",
                # user2 has no access to dc3 because it is owned by user1 and is private
                "data_connector:dc3#delete@user:user2",
                "data_connector:dc3#write@user:user2",
                "data_connector:dc3#read@user:user2",
                # user2 does not have write or delete permissions on dc4
                "data_connector:dc4#delete@user:user2",
                "data_connector:dc4#write@user:user2",
                # user2 can read dc1 because it is owned by a public project
                # anonymous user checks
                "data_connector:dc1#read@user:ANON",
                "data_connector:dc2#read@user:ANON",
                "data_connector:dc3#read@user:ANON",
                "data_connector:dc1#read@anonymous_user:ANON",
                "data_connector:dc2#read@anonymous_user:ANON",
                "data_connector:dc3#read@anonymous_user:ANON",
            ],
        },
    )


@pytest.fixture
def v7_schema() -> SpiceDBSchema:
    return SpiceDBSchema(
        schemas._v7,
        relationships=[
            # public project p1, owner=u1
            "project:p1#owner@user:u1",
            "project:p1#public_viewer@user:*",
            "project:p1#public_viewer@anonymous_user:*",
            "project:p1#editor@user:u11",
            "project:p1#viewer@user:u12",
            # private project p2, owner=u2
            "project:p2#owner@user:u2",
            "project:p2#editor@user:u21",
            "project:p2#viewer@user:u22",
            # private project p3, owner=g1 (group), group owner=u3
            "project:p3#project_namespace@group:g1",
            "group:g1#owner@user:u3",
            "group:g1#editor@user:u4",
            "group:g1#viewer@user:u5",
        ],
        assertions={
            "assertTrue": [
                "project:p1#exclusive_owner@user:u1",
                "project:p1#exclusive_editor@user:u11",
                "project:p1#exclusive_member@user:u1",
                "project:p1#exclusive_member@user:u11",
                "project:p1#exclusive_member@user:u12",
                "project:p2#exclusive_owner@user:u2",
                "project:p2#exclusive_editor@user:u21",
                "project:p2#exclusive_member@user:u2",
                "project:p2#exclusive_member@user:u21",
                "project:p2#exclusive_member@user:u22",
                "project:p3#exclusive_owner@user:u3",
                "group:g1#exclusive_owner@user:u3",
                "project:p3#exclusive_editor@user:u4",
                "group:g1#exclusive_editor@user:u4",
                "project:p3#exclusive_member@user:u5",
                "project:p3#exclusive_member@user:u4",
                "project:p3#exclusive_member@user:u3",
                "group:g1#exclusive_member@user:u5",
                "group:g1#exclusive_member@user:u4",
                "group:g1#exclusive_member@user:u3",
            ],
            "assertFalse": [
                "project:p1#exclusive_owner@user:u2",
                "project:p1#exclusive_editor@user:u1",
                "project:p1#exclusive_editor@user:u12",
                "project:p2#exclusive_owner@user:u1",
                "project:p2#exclusive_editor@user:u2",
                "project:p2#exclusive_editor@user:u22",
            ],
        },
        validation={},
    )


@pytest.fixture
def v9_schema() -> SpiceDBSchema:
    return SpiceDBSchema(
        schemas._v9,
        relationships=[
            "platform:renku#admin@user:admin1",
            # pool1: public
            "resource_pool:pool1#public_viewer@user:*",
            "resource_pool:pool1#public_viewer@anonymous_user:*",
            "resource_pool:pool1#prohibited@user:user2",
            "resource_pool:pool1#resource_pool_platform@platform:renku",
            # pool2: private, only user3 is a viewer
            "resource_pool:pool2#viewer@user:user3",
            "resource_pool:pool2#resource_pool_platform@platform:renku",
            "resource_pool:pool2#prohibited@user:user2",
        ],
        assertions={
            "assertTrue": [
                # pool1 public: prove the pool is public
                "resource_pool:pool1#read@user:user1",
                "resource_pool:pool1#read@anonymous_user:anon1",
                "resource_pool:pool1#read@user:admin1",
                # pool2: pool is only usable by select users
                "resource_pool:pool2#read@user:user3",
                "resource_pool:pool2#read@user:admin1",
                # admin can write
                "resource_pool:pool1#write@user:admin1",
            ],
            "assertFalse": [
                # prohibited user blocked
                "resource_pool:pool1#read@user:user2",
                "resource_pool:pool2#read@user:user2",
                # non-viewer or anon can't use private pool
                "resource_pool:pool2#read@user:user1",
                "resource_pool:pool2#read@anonymous_user:anon1",
                # viewer and random can't write
                "resource_pool:pool2#write@user:user3",
                "resource_pool:pool1#write@user:user1",
            ],
        },
        validation={
            # pool1: (public) list all resolution paths
            "resource_pool:pool1#read": [
                "[user:* - {user:user2}] is <resource_pool:pool1#public_viewer>",
                "[anonymous_user:*] is <resource_pool:pool1#public_viewer>",
                "[user:admin1] is <platform:renku#admin>",
            ],
            # pool2: (private) only viewer + admin, no wildcards
            "resource_pool:pool2#read": [
                "[user:user3] is <resource_pool:pool2#viewer>",
                "[user:admin1] is <platform:renku#admin>",
            ],
            "resource_pool:pool1#write": [
                "[user:admin1] is <platform:renku#admin>",
            ],
            "resource_pool:pool2#write": [
                "[user:admin1] is <platform:renku#admin>",
            ],
        },
    )


@pytest.fixture
def v10_schema() -> SpiceDBSchema:
    return SpiceDBSchema(
        schemas._v10,
        relationships=[
            "platform:renku#admin@user:admin1",
            # pool1: public
            "resource_pool:pool1#public_viewer@user:*",
            "resource_pool:pool1#public_viewer@anonymous_user:*",
            "resource_pool:pool1#prohibited@user:user2",
            "resource_pool:pool1#resource_pool_platform@platform:renku",
            # pool2: private, only user3 is a direct viewer
            "resource_pool:pool2#viewer@user:user3",
            "resource_pool:pool2#resource_pool_platform@platform:renku",
            "resource_pool:pool2#prohibited@user:user2",
            # pool3: private, accessible via a group
            "resource_pool:pool3#resource_pool_platform@platform:renku",
            "resource_pool:pool3#group_viewer@group:group1",
            "resource_pool:pool3#prohibited@user:user2",
            # group1 members: user4 (owner), user5 (editor), user6 (viewer)
            # user2 is also a viewer of the group, but prohibited on the pool
            "group:group1#owner@user:user4",
            "group:group1#editor@user:user5",
            "group:group1#viewer@user:user6",
            "group:group1#viewer@user:user2",
            # pool4: private, accessible via a project
            "resource_pool:pool4#resource_pool_platform@platform:renku",
            "resource_pool:pool4#project_viewer@project:project1",
            "resource_pool:pool4#prohibited@user:user2",
            # project1 members: user7 (owner), user8 (editor), user9 (viewer)
            # user2 is also a viewer on the project, but prohibited on the pool
            "project:project1#owner@user:user7",
            "project:project1#editor@user:user8",
            "project:project1#viewer@user:user9",
            "project:project1#viewer@user:user2",
            # project1 is in a namespace where user10 is the owner; note that
            # namespace-inherited membership must NOT grant pool access because
            # resource_pool uses direct_member (not exclusive_member).
            "user_namespace:ns1#owner@user:user10",
            "project:project1#project_namespace@user_namespace:ns1",
        ],
        assertions={
            "assertTrue": [
                # pool1 public: prove the pool is public
                "resource_pool:pool1#read@user:user1",
                "resource_pool:pool1#read@anonymous_user:anon1",
                "resource_pool:pool1#read@user:admin1",
                # pool2: pool is only usable by select users
                "resource_pool:pool2#read@user:user3",
                "resource_pool:pool2#read@user:admin1",
                # pool3: group members get access via group_viewer->direct_member
                "resource_pool:pool3#read@user:user4",
                "resource_pool:pool3#read@user:user5",
                "resource_pool:pool3#read@user:user6",
                "resource_pool:pool3#read@user:admin1",
                # pool4: project members get access via project_viewer->direct_member
                "resource_pool:pool4#read@user:user7",
                "resource_pool:pool4#read@user:user8",
                "resource_pool:pool4#read@user:user9",
                "resource_pool:pool4#read@user:admin1",
                # admin can write
                "resource_pool:pool1#write@user:admin1",
                "resource_pool:pool3#write@user:admin1",
                "resource_pool:pool4#write@user:admin1",
            ],
            "assertFalse": [
                # prohibited user blocked on all pools
                "resource_pool:pool1#read@user:user2",
                "resource_pool:pool2#read@user:user2",
                "resource_pool:pool3#read@user:user2",
                "resource_pool:pool4#read@user:user2",
                # non-viewer or anon can't use private pool
                "resource_pool:pool2#read@user:user1",
                "resource_pool:pool2#read@anonymous_user:anon1",
                # non-group-member can't access pool3
                "resource_pool:pool3#read@user:user1",
                "resource_pool:pool3#read@anonymous_user:anon1",
                # non-project-member can't access pool4
                "resource_pool:pool4#read@user:user1",
                "resource_pool:pool4#read@anonymous_user:anon1",
                # namespace owner is not a direct_member of the project,
                # so they do NOT get pool4 access
                "resource_pool:pool4#read@user:user10",
                # viewer and random can't write
                "resource_pool:pool2#write@user:user3",
                "resource_pool:pool1#write@user:user1",
                "resource_pool:pool3#write@user:user4",
                "resource_pool:pool4#write@user:user7",
            ],
        },
        validation={
            # pool1: (public) list all resolution paths
            "resource_pool:pool1#read": [
                "[user:* - {user:user2}] is <resource_pool:pool1#public_viewer>",
                "[anonymous_user:*] is <resource_pool:pool1#public_viewer>",
                "[user:admin1] is <platform:renku#admin>",
            ],
            # pool2: (private) only viewer + admin, no wildcards
            "resource_pool:pool2#read": [
                "[user:user3] is <resource_pool:pool2#viewer>",
                "[user:admin1] is <platform:renku#admin>",
            ],
            # pool3: (private) access via group_viewer->direct_member + admin
            "resource_pool:pool3#read": [
                "[user:user4] is <group:group1#owner>",
                "[user:user5] is <group:group1#editor>",
                "[user:user6] is <group:group1#viewer>",
                "[user:admin1] is <platform:renku#admin>",
            ],
            # pool4: (private) access via project_viewer->direct_member + admin
            "resource_pool:pool4#read": [
                "[user:user7] is <project:project1#owner>",
                "[user:user8] is <project:project1#editor>",
                "[user:user9] is <project:project1#viewer>",
                "[user:admin1] is <platform:renku#admin>",
            ],
            "resource_pool:pool1#write": [
                "[user:admin1] is <platform:renku#admin>",
            ],
            "resource_pool:pool2#write": [
                "[user:admin1] is <platform:renku#admin>",
            ],
            "resource_pool:pool3#write": [
                "[user:admin1] is <platform:renku#admin>",
            ],
            "resource_pool:pool4#write": [
                "[user:admin1] is <platform:renku#admin>",
            ],
        },
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


def test_v6_schema(tmp_path: Path, v6_schema: SpiceDBSchema) -> None:
    validation_file = tmp_path / "validate.yaml"
    v6_schema.to_yaml(validation_file)
    check_call(["zed", "validate", validation_file.as_uri()])


def test_v7_schema(tmp_path: Path, v7_schema: SpiceDBSchema) -> None:
    validation_file = tmp_path / "validate.yaml"
    v7_schema.to_yaml(validation_file)
    check_call(["zed", "validate", validation_file.as_uri()])


def test_v9_schema(tmp_path: Path, v9_schema: SpiceDBSchema) -> None:
    validation_file = tmp_path / "validate.yaml"
    v9_schema.to_yaml(validation_file)
    check_call(["zed", "validate", validation_file.as_uri()])


def test_v10_schema(tmp_path: Path, v10_schema: SpiceDBSchema) -> None:
    validation_file = tmp_path / "validate.yaml"
    v10_schema.to_yaml(validation_file)
    check_call(["zed", "validate", validation_file.as_uri()])
