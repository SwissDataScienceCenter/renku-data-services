"""add zenodo provider kind

Revision ID: 53ef858f34ea
Revises: 287879848fb3
Create Date: 2026-02-20 16:45:47.200173

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "53ef858f34ea"
down_revision = "287879848fb3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE providerkind ADD VALUE 'zenodo'")


def downgrade() -> None:
    # NOTE: Postgres does not allow removing values from an enum
    op.execute("DELETE FROM connected_services.oauth2_clients WHERE kind = 'zenodo'")
    op.execute("ALTER TYPE providerkind RENAME TO providerkind_old;")
    op.execute("CREATE TYPE providerkind AS ENUM ('gitlab', 'github', 'drive', 'onedrive', 'dropbox', 'generic_oidc')")
    op.execute(
        "ALTER TABLE connected_services.oauth2_clients ALTER COLUMN kind SET DATA TYPE providerkind USING kind::text::providerkind"
    )
    op.execute("DROP TYPE providerkind_old CASCADE")
