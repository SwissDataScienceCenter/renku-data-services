"""add generic_oidc provider type

Revision ID: fe61e825d95e
Revises: f6705f482551
Create Date: 2025-09-05 09:30:23.062585

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "fe61e825d95e"
down_revision = "f6705f482551"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE providerkind ADD VALUE 'generic_oidc'")
    op.add_column(
        "oauth2_clients", sa.Column("oidc_issuer_url", sa.String(), nullable=True), schema="connected_services"
    )


def downgrade() -> None:
    op.drop_column("oauth2_clients", "oidc_issuer_url", schema="connected_services")
    # NOTE: Postgres does not allow removing values from an enum
    op.execute("DELETE FROM connected_services.oauth2_clients WHERE kind = 'generic_oidc'")
    op.execute("ALTER TYPE providerkind RENAME TO providerkind_old;")
    op.execute("CREATE TYPE providerkind AS ENUM ('gitlab', 'github', 'drive', 'onedrive', 'dropbox')")
    op.execute(
        "ALTER TABLE connected_services.oauth2_clients ALTER COLUMN kind SET DATA TYPE providerkind USING kind::text::providerkind"
    )
    op.execute("DROP TYPE providerkind_old CASCADE")
