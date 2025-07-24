"""set check constraint for data connectors and projects in entity slugs table

Revision ID: 2d3bf387ef9a
Revises: 322f8c5f4eb0
Create Date: 2025-03-19 09:51:46.505682

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "2d3bf387ef9a"
down_revision = "322f8c5f4eb0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "one_or_both_project_id_or_group_id_are_set",
        "entity_slugs",
        "(project_id IS NOT NULL) OR (data_connector_id IS NOT NULL)",
        schema="common",
    )


def downgrade() -> None:
    op.drop_constraint(
        "one_or_both_project_id_or_group_id_are_set",
        "entity_slugs",
        schema="common",
        type_="check",
    )
