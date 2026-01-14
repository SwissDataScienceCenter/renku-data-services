"""upgrade oauth provider kind enum

Revision ID: 58ad5426c2f3
Revises: 9b18adb58e63
Create Date: 2026-01-14 14:35:29.539830

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "58ad5426c2f3"
down_revision = "9b18adb58e63"
branch_labels = None
depends_on = None

# NOTE: Postgres does not allow removing values from an enum


def upgrade() -> None:
    op.execute("DELETE FROM connected_services.oauth2_clients WHERE kind = 'drive'")
    op.execute("DELETE FROM connected_services.oauth2_clients WHERE kind = 'onedrive'")
    op.execute("DELETE FROM connected_services.oauth2_clients WHERE kind = 'dropbox'")
    op.execute("ALTER TYPE providerkind RENAME TO providerkind_old")
    op.execute("CREATE TYPE providerkind AS ENUM ('gitlab', 'github', 'google', 'generic_oidc')")
    op.execute(
        "ALTER TABLE connected_services.oauth2_clients ALTER COLUMN kind SET DATA TYPE providerkind USING kind::text::providerkind"
    )
    op.execute("DROP TYPE providerkind_old CASCADE")


def downgrade() -> None:
    op.execute("DELETE FROM connected_services.oauth2_clients WHERE kind = 'google'")
    op.execute("ALTER TYPE providerkind RENAME TO providerkind_old")
    op.execute("CREATE TYPE providerkind AS ENUM ('gitlab', 'github', 'drive', 'onedrive', 'dropbox', 'generic_oidc')")
    op.execute(
        "ALTER TABLE connected_services.oauth2_clients ALTER COLUMN kind SET DATA TYPE providerkind USING kind::text::providerkind"
    )
    op.execute("DROP TYPE providerkind_old CASCADE")
