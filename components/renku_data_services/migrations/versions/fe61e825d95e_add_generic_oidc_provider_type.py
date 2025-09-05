"""add generic_oidc provider type

Revision ID: fe61e825d95e
Revises: 35ea9d8f54e8
Create Date: 2025-09-05 09:30:23.062585

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "fe61e825d95e"
down_revision = "35ea9d8f54e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE providerkind ADD VALUE 'generic_oidc'")


def downgrade() -> None:
    # NOTE: Postgres does not allow removing values from an enum
    op.execute("DELETE FROM connected_services.oauth2_clients WHERE kind = 'generic_oidc'")
    op.execute("ALTER TYPE providerkind RENAME TO providerkind_old;")
    op.execute("CREATE TYPE providerkind AS ENUM ('gitlab', 'github', 'drive', 'onedrive', 'dropbox')")
    op.execute(
        "ALTER TABLE connected_services.oauth2_clients ALTER COLUMN kind SET DATA TYPE providerkind USING kind::text::providerkind"
    )
    op.execute("DROP TYPE providerkind_old CASCADE")
