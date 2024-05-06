"""Specification of SpiceDB schemas.

These are applied through alembic migrations in the commoin migrations folder.
"""

v1: str = """\
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

v2: str = """\
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
    permission read = is_owner
    permission write = is_owner
    permission is_owner = owner + user_namespace_platform->is_admin
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
    permission delete = owner + project_platform->is_admin + project_namespace->delete + project_namespace->is_owner
}"""
