"""add dockerhub provider kind

Revision ID: c7d32e8b52cf
Revises: 8365db35dc76
Create Date: 2025-09-25 14:05:55.447619

"""

from alembic import op

import renku_data_services.migrations.helper as helper

# revision identifiers, used by Alembic.
revision = "c7d32e8b52cf"
down_revision = "8365db35dc76"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE providerkind ADD VALUE 'dockerhub'")


def downgrade() -> None:
    op.execute("DELETE FROM connected_services.oauth2_clients WHERE kind = 'dockerhub'")

    current_values = helper.get_enum_values("providerkind")
    current_values.remove("dockerhub")

    op.execute("ALTER TYPE providerkind RENAME TO providerkind_old;")
    helper.create_enum_type("providerkind", current_values)
    op.execute(
        "ALTER TABLE connected_services.oauth2_clients ALTER COLUMN kind SET DATA TYPE providerkind USING kind::text::providerkind"
    )

    op.execute("DROP TYPE providerkind_old CASCADE")
