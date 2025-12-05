"""Specification of SpiceDB schemas.

These are applied through alembic migrations in the common migrations folder.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast

from authzed.api.v1 import (
    DeleteRelationshipsRequest,
    DeleteRelationshipsResponse,
    Relationship,
    RelationshipFilter,
    RelationshipUpdate,
    SubjectFilter,
    SubjectReference,
    SyncClient,
    WriteRelationshipsRequest,
    WriteSchemaRequest,
    WriteSchemaResponse,
)
from ulid import ULID

from renku_data_services.authz.authz import _AuthzConverter, _Relation
from renku_data_services.base_models.core import ResourceType
from renku_data_services.errors import errors


@dataclass
class AuthzSchemaMigration:
    """A representation of an Authzed DB schema used for migrations."""

    up: list[WriteRelationshipsRequest | DeleteRelationshipsRequest | WriteSchemaRequest]
    down: list[WriteRelationshipsRequest | DeleteRelationshipsRequest | WriteSchemaRequest]

    @staticmethod
    def _write_to_db(
        requests: list[WriteRelationshipsRequest | DeleteRelationshipsRequest | WriteSchemaRequest], client: SyncClient
    ) -> list[WriteSchemaResponse | DeleteRelationshipsResponse | WriteSchemaResponse]:
        output: list[WriteSchemaResponse | DeleteRelationshipsResponse | WriteSchemaResponse] = []
        for request in requests:
            match request:
                case WriteRelationshipsRequest():
                    res = client.WriteRelationships(request)
                    output.append(res)
                case DeleteRelationshipsRequest():
                    res = client.DeleteRelationships(request)
                    output.append(res)
                case WriteSchemaRequest():
                    res = client.WriteSchema(request)
                    output.append(res)
                case _:
                    raise errors.ProgrammingError(
                        message=f"Found an unknown authorization migration type {type(request)}"
                    )
        return output

    def upgrade(
        self, client: SyncClient
    ) -> list[WriteSchemaResponse | DeleteRelationshipsResponse | WriteSchemaResponse]:
        """Perform the required changes to upgrade the authorization database schema."""
        return self._write_to_db(self.up, client)

    def downgrade(
        self, client: SyncClient
    ) -> list[WriteSchemaResponse | DeleteRelationshipsResponse | WriteSchemaResponse]:
        """Perform the required changes to downgrade the authorization database schema."""
        return self._write_to_db(self.down, client)


_v1: str = """\
definition user {}

definition anonymous_user {}

definition platform {
    relation admin: user
    permission is_admin = admin
}

definition project {
    relation project_platform: platform
    relation owner: user
    relation editor: user
    relation viewer: user | user:* | anonymous_user:*
    permission read = viewer + write
    permission write = editor + delete
    permission change_membership = delete
    permission delete = owner + project_platform->is_admin
}"""

v1 = AuthzSchemaMigration(
    up=[WriteSchemaRequest(schema=_v1)],
    down=[
        DeleteRelationshipsRequest(
            relationship_filter=RelationshipFilter(
                resource_type=ResourceType.project.value, optional_relation=_Relation.project_platform.value
            )
        ),
        DeleteRelationshipsRequest(
            relationship_filter=RelationshipFilter(
                resource_type=ResourceType.platform.value, optional_relation=_Relation.admin.value
            )
        ),
        DeleteRelationshipsRequest(
            relationship_filter=RelationshipFilter(
                resource_type=ResourceType.project.value, optional_relation=_Relation.owner.value
            )
        ),
        DeleteRelationshipsRequest(
            relationship_filter=RelationshipFilter(
                resource_type=ResourceType.project.value, optional_relation=_Relation.editor.value
            )
        ),
        DeleteRelationshipsRequest(
            relationship_filter=RelationshipFilter(
                resource_type=ResourceType.project.value, optional_relation=_Relation.viewer.value
            )
        ),
    ],
)

_v2: str = """\
definition user {}

definition group {
    relation group_platform: platform
    relation owner: user
    relation editor: user
    relation viewer: user | user:* | anonymous_user:*
    permission read = viewer + write
    permission write = editor + delete
    permission change_membership = delete
    permission delete = owner + group_platform->is_admin
}

definition user_namespace {
    relation user_namespace_platform: platform
    relation owner: user
    permission read = delete
    permission write = delete
    permission delete = owner + user_namespace_platform->is_admin
}

definition anonymous_user {}

definition platform {
    relation admin: user
    permission is_admin = admin
}

definition project {
    relation project_platform: platform
    relation project_namespace: user_namespace | group
    relation owner: user
    relation editor: user
    relation viewer: user | user:* | anonymous_user:*
    permission read = viewer + write + project_namespace->read
    permission write = editor + delete + project_namespace->write
    permission change_membership = delete
    permission delete = owner + project_platform->is_admin + project_namespace->delete
}"""

v2 = AuthzSchemaMigration(
    up=[WriteSchemaRequest(schema=_v2)],
    down=[
        DeleteRelationshipsRequest(
            relationship_filter=RelationshipFilter(
                resource_type=ResourceType.project.value, optional_relation=_Relation.project_namespace.value
            )
        ),
        DeleteRelationshipsRequest(
            relationship_filter=RelationshipFilter(
                resource_type=ResourceType.user_namespace.value,
                optional_relation=_Relation.user_namespace_platform.value,
            )
        ),
        DeleteRelationshipsRequest(
            relationship_filter=RelationshipFilter(
                resource_type=ResourceType.user_namespace.value, optional_relation=_Relation.owner.value
            )
        ),
        DeleteRelationshipsRequest(
            relationship_filter=RelationshipFilter(
                resource_type=ResourceType.group.value, optional_relation=_Relation.group_platform.value
            )
        ),
        DeleteRelationshipsRequest(
            relationship_filter=RelationshipFilter(
                resource_type=ResourceType.group.value, optional_relation=_Relation.owner.value
            )
        ),
        DeleteRelationshipsRequest(
            relationship_filter=RelationshipFilter(
                resource_type=ResourceType.group.value, optional_relation=_Relation.editor.value
            )
        ),
        DeleteRelationshipsRequest(
            relationship_filter=RelationshipFilter(
                resource_type=ResourceType.group.value, optional_relation=_Relation.viewer.value
            )
        ),
        WriteSchemaRequest(schema=_v1),
    ],
)

_v3: str = """\
definition user {}

definition group {
    relation group_platform: platform
    relation owner: user
    relation editor: user
    relation viewer: user
    relation public_viewer: user:* | anonymous_user:*
    permission read = public_viewer + read_children
    permission read_children = viewer + write
    permission write = editor + delete
    permission change_membership = delete
    permission delete = owner + group_platform->is_admin
}

definition user_namespace {
    relation user_namespace_platform: platform
    relation owner: user
    relation public_viewer: user:* | anonymous_user:*
    permission read = public_viewer + read_children
    permission read_children = delete
    permission write = delete
    permission delete = owner + user_namespace_platform->is_admin
}

definition anonymous_user {}

definition platform {
    relation admin: user
    permission is_admin = admin
}

definition project {
    relation project_platform: platform
    relation project_namespace: user_namespace | group
    relation owner: user
    relation editor: user
    relation viewer: user | user:* | anonymous_user:*
    permission read = viewer + write + project_namespace->read_children
    permission write = editor + delete + project_namespace->write
    permission change_membership = delete
    permission delete = owner + project_platform->is_admin + project_namespace->delete
}"""

v3 = AuthzSchemaMigration(
    up=[
        DeleteRelationshipsRequest(
            relationship_filter=RelationshipFilter(
                resource_type=ResourceType.group.value,
                optional_relation=_Relation.viewer.value,
                optional_subject_filter=SubjectFilter(
                    subject_type=ResourceType.user.value,
                    optional_subject_id=SubjectReference(object=_AuthzConverter.all_users()).object.object_id,
                ),
            )
        ),
        DeleteRelationshipsRequest(
            relationship_filter=RelationshipFilter(
                resource_type=ResourceType.group.value,
                optional_relation=_Relation.viewer.value,
                optional_subject_filter=SubjectFilter(
                    subject_type=ResourceType.anonymous_user.value,
                    optional_subject_id=SubjectReference(object=_AuthzConverter.anonymous_users()).object.object_id,
                ),
            )
        ),
        WriteSchemaRequest(schema=_v3),
    ],
    down=[
        DeleteRelationshipsRequest(
            relationship_filter=RelationshipFilter(
                resource_type=ResourceType.group.value, optional_relation=_Relation.public_viewer.value
            )
        ),
        DeleteRelationshipsRequest(
            relationship_filter=RelationshipFilter(
                resource_type=ResourceType.user_namespace.value, optional_relation=_Relation.public_viewer.value
            )
        ),
        WriteSchemaRequest(schema=_v2),
    ],
)

_v4: str = """\
definition user {}

definition group {
    relation group_platform: platform
    relation owner: user
    relation editor: user
    relation viewer: user
    relation public_viewer: user:* | anonymous_user:*
    permission read = public_viewer + read_children
    permission read_children = viewer + write
    permission write = editor + delete
    permission change_membership = delete
    permission delete = owner + group_platform->is_admin
}

definition user_namespace {
    relation user_namespace_platform: platform
    relation owner: user
    relation public_viewer: user:* | anonymous_user:*
    permission read = public_viewer + read_children
    permission read_children = delete
    permission write = delete
    permission delete = owner + user_namespace_platform->is_admin
}

definition anonymous_user {}

definition platform {
    relation admin: user
    permission is_admin = admin
}

definition project {
    relation project_platform: platform
    relation project_namespace: user_namespace | group
    relation owner: user
    relation editor: user
    relation viewer: user
    relation public_viewer: user:* | anonymous_user:*
    permission read = public_viewer + viewer + write + project_namespace->read_children
    permission read_linked_resources = viewer + editor + owner + project_platform->is_admin
    permission write = editor + delete + project_namespace->write
    permission change_membership = delete
    permission delete = owner + project_platform->is_admin + project_namespace->delete
}

definition data_connector {
    relation data_connector_platform: platform
    relation data_connector_namespace: user_namespace | group
    relation linked_to: project
    relation owner: user
    relation editor: user
    relation viewer: user
    relation public_viewer: user:* | anonymous_user:*
    permission read = public_viewer + viewer + write + \
        data_connector_namespace->read_children + read_from_linked_resource
    permission read_from_linked_resource = linked_to->read_linked_resources
    permission write = editor + delete + data_connector_namespace->write
    permission change_membership = delete
    permission delete = owner + data_connector_platform->is_admin + data_connector_namespace->delete
    permission add_link = write + public_viewer
}"""


def generate_v4(public_project_ids: Iterable[str]) -> AuthzSchemaMigration:
    """Creates the v4 schema migration."""
    up: list[WriteRelationshipsRequest | DeleteRelationshipsRequest | WriteSchemaRequest] = [
        DeleteRelationshipsRequest(
            relationship_filter=RelationshipFilter(
                resource_type=ResourceType.project.value,
                optional_relation=_Relation.viewer.value,
                optional_subject_filter=SubjectFilter(
                    subject_type=ResourceType.user.value,
                    optional_subject_id=SubjectReference(object=_AuthzConverter.all_users()).object.object_id,
                ),
            )
        ),
        DeleteRelationshipsRequest(
            relationship_filter=RelationshipFilter(
                resource_type=ResourceType.project.value,
                optional_relation=_Relation.viewer.value,
                optional_subject_filter=SubjectFilter(
                    subject_type=ResourceType.anonymous_user.value,
                    optional_subject_id=SubjectReference(object=_AuthzConverter.anonymous_users()).object.object_id,
                ),
            )
        ),
        WriteSchemaRequest(schema=_v4),
    ]
    down: list[WriteRelationshipsRequest | DeleteRelationshipsRequest | WriteSchemaRequest] = [
        DeleteRelationshipsRequest(
            relationship_filter=RelationshipFilter(
                resource_type=ResourceType.project.value, optional_relation=_Relation.public_viewer.value
            )
        ),
        DeleteRelationshipsRequest(
            relationship_filter=RelationshipFilter(resource_type=ResourceType.data_connector.value)
        ),
        WriteSchemaRequest(schema=_v3),
    ]

    all_users_sub = SubjectReference(object=_AuthzConverter.all_users())
    anon_users_sub = SubjectReference(object=_AuthzConverter.anonymous_users())
    for project_id in public_project_ids:
        project_res = _AuthzConverter.project(cast(ULID, ULID.from_str(project_id)))
        all_users_are_viewers = Relationship(
            resource=project_res,
            relation=_Relation.public_viewer.value,
            subject=all_users_sub,
        )
        anon_users_are_viewers = Relationship(
            resource=project_res,
            relation=_Relation.public_viewer.value,
            subject=anon_users_sub,
        )
        down_all_users_are_viewers = Relationship(
            resource=project_res,
            relation=_Relation.viewer.value,
            subject=all_users_sub,
        )
        down_anon_users_are_viewers = Relationship(
            resource=project_res,
            relation=_Relation.viewer.value,
            subject=anon_users_sub,
        )
        up.append(
            WriteRelationshipsRequest(
                updates=[
                    RelationshipUpdate(
                        operation=RelationshipUpdate.OPERATION_TOUCH, relationship=all_users_are_viewers
                    ),
                    RelationshipUpdate(
                        operation=RelationshipUpdate.OPERATION_TOUCH, relationship=anon_users_are_viewers
                    ),
                ],
            )
        )
        down.append(
            WriteRelationshipsRequest(
                updates=[
                    RelationshipUpdate(
                        operation=RelationshipUpdate.OPERATION_TOUCH, relationship=down_all_users_are_viewers
                    ),
                    RelationshipUpdate(
                        operation=RelationshipUpdate.OPERATION_TOUCH, relationship=down_anon_users_are_viewers
                    ),
                ],
            )
        )

    return AuthzSchemaMigration(up=up, down=down)


_v5: str = """\
definition user {}

definition group {
    relation group_platform: platform
    relation owner: user
    relation editor: user
    relation viewer: user
    relation public_viewer: user:* | anonymous_user:*
    permission read = public_viewer + read_children
    permission read_children = viewer + write
    permission write = editor + delete
    permission change_membership = delete
    permission delete = owner + group_platform->is_admin
    permission non_public_read = owner + editor + viewer - public_viewer
}

definition user_namespace {
    relation user_namespace_platform: platform
    relation owner: user
    relation public_viewer: user:* | anonymous_user:*
    permission read = public_viewer + read_children
    permission read_children = delete
    permission write = delete
    permission delete = owner + user_namespace_platform->is_admin
    permission non_public_read = owner - public_viewer
}

definition anonymous_user {}

definition platform {
    relation admin: user
    permission is_admin = admin
}

definition project {
    relation project_platform: platform
    relation project_namespace: user_namespace | group
    relation owner: user
    relation editor: user
    relation viewer: user
    relation public_viewer: user:* | anonymous_user:*
    permission read = public_viewer + viewer + write + project_namespace->read_children
    permission read_linked_resources = viewer + editor + owner + project_platform->is_admin
    permission write = editor + delete + project_namespace->write
    permission change_membership = delete
    permission delete = owner + project_platform->is_admin + project_namespace->delete
    permission non_public_read = owner + editor + viewer + project_namespace->read_children - public_viewer
}

definition data_connector {
    relation data_connector_platform: platform
    relation data_connector_namespace: user_namespace | group
    relation linked_to: project
    relation owner: user
    relation editor: user
    relation viewer: user
    relation public_viewer: user:* | anonymous_user:*
    permission read = public_viewer + viewer + write + \
    data_connector_namespace->read_children + read_from_linked_resource
    permission read_from_linked_resource = linked_to->read_linked_resources
    permission write = editor + delete + data_connector_namespace->write
    permission change_membership = delete
    permission delete = owner + data_connector_platform->is_admin + data_connector_namespace->delete
    permission add_link = write + public_viewer
    permission non_public_read = owner + editor + viewer + data_connector_namespace->read_children - public_viewer
}"""

v5 = AuthzSchemaMigration(
    up=[WriteSchemaRequest(schema=_v5)],
    down=[WriteSchemaRequest(schema=_v4)],
)

_v6: str = """\
definition user {}

definition group {
    relation group_platform: platform
    relation owner: user
    relation editor: user
    relation viewer: user
    relation public_viewer: user:* | anonymous_user:*
    permission read = public_viewer + read_children
    permission read_children = viewer + write
    permission write = editor + delete
    permission change_membership = delete
    permission delete = owner + group_platform->is_admin
    permission non_public_read = owner + editor + viewer - public_viewer
}

definition user_namespace {
    relation user_namespace_platform: platform
    relation owner: user
    relation public_viewer: user:* | anonymous_user:*
    permission read = public_viewer + read_children
    permission read_children = delete
    permission write = delete
    permission delete = owner + user_namespace_platform->is_admin
    permission non_public_read = owner - public_viewer
}

definition anonymous_user {}

definition platform {
    relation admin: user
    permission is_admin = admin
}

definition project {
    relation project_platform: platform
    relation project_namespace: user_namespace | group
    relation owner: user
    relation editor: user
    relation viewer: user
    relation public_viewer: user:* | anonymous_user:*
    permission read = public_viewer + read_children
    permission read_children = viewer + write + project_namespace->read_children
    permission write = editor + delete + project_namespace->write
    permission change_membership = delete
    permission delete = owner + project_platform->is_admin + project_namespace->delete
    permission non_public_read = owner + editor + viewer + project_namespace->read_children - public_viewer
}

definition data_connector {
    relation data_connector_platform: platform
    relation data_connector_namespace: user_namespace | group | project
    relation linked_to: project
    relation owner: user
    relation editor: user
    relation viewer: user
    relation public_viewer: user:* | anonymous_user:*
    permission read = public_viewer + viewer + write + data_connector_namespace->read_children
    permission write = editor + delete + data_connector_namespace->write
    permission change_membership = delete
    permission delete = owner + data_connector_platform->is_admin + data_connector_namespace->delete
    permission non_public_read = owner + editor + viewer + data_connector_namespace->read_children - public_viewer
}"""

v6 = AuthzSchemaMigration(
    up=[WriteSchemaRequest(schema=_v6)],
    down=[WriteSchemaRequest(schema=_v5)],
)

_v7 = """\
definition user {}

definition group {
    relation group_platform: platform
    relation owner: user
    relation editor: user
    relation viewer: user
    relation public_viewer: user:* | anonymous_user:*
    permission read = public_viewer + read_children
    permission read_children = viewer + write
    permission write = editor + delete
    permission change_membership = delete
    permission delete = owner + group_platform->is_admin
    permission non_public_read = owner + editor + viewer - public_viewer
    permission exclusive_owner = owner
    permission exclusive_editor = editor
    permission exclusive_member = viewer + editor + owner
    permission direct_member = owner + editor + viewer
}

definition user_namespace {
    relation user_namespace_platform: platform
    relation owner: user
    relation public_viewer: user:* | anonymous_user:*
    permission read = public_viewer + read_children
    permission read_children = delete
    permission write = delete
    permission delete = owner + user_namespace_platform->is_admin
    permission non_public_read = owner - public_viewer
    permission exclusive_owner = owner
    permission exclusive_member = owner
    permission direct_member = owner
}

definition anonymous_user {}

definition platform {
    relation admin: user
    permission is_admin = admin
}

definition project {
    relation project_platform: platform
    relation project_namespace: user_namespace | group
    relation owner: user
    relation editor: user
    relation viewer: user
    relation public_viewer: user:* | anonymous_user:*
    permission read = public_viewer + read_children
    permission read_children = viewer + write + project_namespace->read_children
    permission write = editor + delete + project_namespace->write
    permission change_membership = delete
    permission delete = owner + project_platform->is_admin + project_namespace->delete
    permission non_public_read = owner + editor + viewer + project_namespace->read_children - public_viewer
    permission exclusive_owner = owner + project_namespace->exclusive_owner
    permission exclusive_editor = editor + project_namespace->exclusive_editor
    permission exclusive_member = owner + editor + viewer + project_namespace->exclusive_member
    permission direct_member = owner + editor + viewer
}

definition data_connector {
    relation data_connector_platform: platform
    relation data_connector_namespace: user_namespace | group | project
    relation linked_to: project
    relation owner: user
    relation editor: user
    relation viewer: user
    relation public_viewer: user:* | anonymous_user:*
    permission read = public_viewer + viewer + write + data_connector_namespace->read_children
    permission write = editor + delete + data_connector_namespace->write
    permission change_membership = delete
    permission delete = owner + data_connector_platform->is_admin + data_connector_namespace->delete
    permission non_public_read = owner + editor + viewer + data_connector_namespace->read_children - public_viewer
    permission exclusive_owner = owner + data_connector_namespace->exclusive_owner
    permission exclusive_editor = editor + data_connector_namespace->exclusive_editor
    permission exclusive_member = owner + editor + viewer + data_connector_namespace->exclusive_member
    permission direct_member = owner + editor + viewer
}"""
"""This adds three permissions starting with `exclusive_` that are identifying the path of a role.

They are used for reverse lookups (LookupResources) to determine which
objects a specific user is an owner, editor or member.
"""

v7 = AuthzSchemaMigration(
    up=[WriteSchemaRequest(schema=_v7)],
    down=[WriteSchemaRequest(schema=_v6)],
)


_v8 = """\
definition user {}

definition group {
    relation group_platform: platform
    relation owner: user
    relation editor: user
    relation viewer: user
    relation public_viewer: user:* | anonymous_user:*
    permission read = public_viewer + read_children
    permission read_children = viewer + write
    permission write = editor + delete
    permission change_membership = delete
    permission delete = owner + group_platform->is_admin
    permission non_public_read = owner + editor + viewer - public_viewer
    permission exclusive_owner = owner
    permission exclusive_editor = editor
    permission exclusive_member = viewer + editor + owner
    permission direct_member = owner + editor + viewer
}

definition user_namespace {
    relation user_namespace_platform: platform
    relation owner: user
    relation public_viewer: user:* | anonymous_user:*
    permission read = public_viewer + read_children
    permission read_children = delete
    permission write = delete
    permission delete = owner + user_namespace_platform->is_admin
    permission non_public_read = owner - public_viewer
    permission exclusive_owner = owner
    permission exclusive_member = owner
    permission direct_member = owner
}

definition anonymous_user {}

definition platform {
    relation admin: user
    permission is_admin = admin
}

definition project {
    relation project_platform: platform
    relation project_namespace: user_namespace | group
    relation owner: user
    relation editor: user
    relation viewer: user
    relation public_viewer: user:* | anonymous_user:*
    permission read = public_viewer + read_children
    permission read_children = viewer + write + project_namespace->read_children
    permission write = editor + delete
    permission change_membership = delete
    permission delete = owner + project_platform->is_admin + project_namespace->delete
    permission non_public_read = owner + editor + viewer + project_namespace->read_children - public_viewer
    permission exclusive_owner = owner + project_namespace->exclusive_owner
    permission exclusive_editor = editor
    permission exclusive_member = owner + editor + viewer + project_namespace->exclusive_member
    permission direct_member = owner + editor + viewer
}

definition data_connector {
    relation data_connector_platform: platform
    relation data_connector_namespace: user_namespace | group | project
    relation linked_to: project
    relation owner: user
    relation editor: user
    relation viewer: user
    relation public_viewer: user:* | anonymous_user:*
    permission read = public_viewer + viewer + write + data_connector_namespace->read_children
    permission write = editor + delete
    permission change_membership = delete
    permission delete = owner + data_connector_platform->is_admin + data_connector_namespace->delete
    permission non_public_read = owner + editor + viewer + data_connector_namespace->read_children - public_viewer
    permission exclusive_owner = owner + data_connector_namespace->exclusive_owner
    permission exclusive_editor = editor
    permission exclusive_member = owner + editor + viewer + data_connector_namespace->exclusive_member
    permission direct_member = owner + editor + viewer
}"""
"""This modifies how group permissions are inherited on projects and data connectors.
"""

v8 = AuthzSchemaMigration(
    up=[WriteSchemaRequest(schema=_v8)],
    down=[WriteSchemaRequest(schema=_v7)],
)
