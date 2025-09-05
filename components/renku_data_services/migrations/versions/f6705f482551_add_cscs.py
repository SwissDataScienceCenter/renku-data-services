"""add cscs

Revision ID: f6705f482551
Revises: 5343f6d1ef51
Create Date: 2025-06-17 14:09:43.322460

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "f6705f482551"
down_revision = "5343f6d1ef51"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE providerkind ADD VALUE 'cscs'")


def downgrade() -> None:
    # NOTE: Postgres does not allow removing values from an enum
    op.execute("DELETE FROM connected_services.oauth2_clients WHERE kind = 'cscs'")
    op.execute("ALTER TYPE providerkind RENAME TO providerkind_old;")
    op.execute("CREATE TYPE providerkind AS ENUM ('gitlab', 'github', 'drive', 'onedrive', 'dropbox')")
    op.execute(
        "ALTER TABLE connected_services.oauth2_clients ALTER COLUMN kind SET DATA TYPE providerkind USING kind::text::providerkind"
    )
    op.execute("DROP TYPE providerkind_old CASCADE")
