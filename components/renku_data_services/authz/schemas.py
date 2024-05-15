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
