"""Specification of SpiceDB schemas.

These are applied through alembic migrations in the common migrations folder.
"""

from dataclasses import dataclass

from authzed.api.v1 import SyncClient
from authzed.api.v1.core_pb2 import SubjectReference
from authzed.api.v1.permission_service_pb2 import (
    DeleteRelationshipsRequest,
    DeleteRelationshipsResponse,
    RelationshipFilter,
    SubjectFilter,
    WriteRelationshipsRequest,
)
from authzed.api.v1.schema_service_pb2 import WriteSchemaRequest, WriteSchemaResponse

from renku_data_services.authz.authz import ResourceType, _AuthzConverter, _Relation
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
