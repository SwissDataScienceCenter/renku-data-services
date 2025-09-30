"""remove cscs

Revision ID: 4aa2ab4dface
Revises: 97de1962e448
Create Date: 2025-09-30 07:04:55.079405

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "4aa2ab4dface"
down_revision = "97de1962e448"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NOTE: Postgres does not allow removing values from an enum
    op.execute("DELETE FROM connected_services.oauth2_clients WHERE kind = 'cscs'")
    op.execute("ALTER TYPE providerkind RENAME TO providerkind_old;")
    op.execute("CREATE TYPE providerkind AS ENUM ('gitlab', 'github', 'drive', 'onedrive', 'dropbox', 'generic_oidc')")
    op.execute(
        "ALTER TABLE connected_services.oauth2_clients ALTER COLUMN kind SET DATA TYPE providerkind USING kind::text::providerkind"
    )
    op.execute("DROP TYPE providerkind_old CASCADE")


def downgrade() -> None:
    op.execute("ALTER TYPE providerkind ADD VALUE 'cscs'")
