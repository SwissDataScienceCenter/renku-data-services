"""add scicat in deposit sources and providerkind

Revision ID: 3016b9c4de5e
Revises: fc1a97661d0c
Create Date: 2026-09-17 09:27:07.748259

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "3016b9c4de5e"
down_revision = "fc1a97661d0c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("INSERT INTO storage.deposit_sources (source) VALUES ('scicat') ON CONFLICT DO NOTHING")
    op.execute("ALTER TYPE providerkind ADD VALUE 'scicat'")


def downgrade() -> None:
    op.execute("DELETE FROM storage.deposit_sources WHERE source = 'scicat'")
    # NOTE: Postgres does not allow removing values from an enum
    op.execute("DELETE FROM connected_services.oauth2_clients WHERE kind = 'scicat'")
    op.execute("ALTER TYPE providerkind RENAME TO providerkind_old;")
    op.execute("CREATE TYPE providerkind AS ENUM ('dropbox', 'generic_oidc', 'github', 'gitlab', 'google', 'zenodo')")
    op.execute(
        "ALTER TABLE connected_services.oauth2_clients ALTER COLUMN kind SET DATA TYPE providerkind USING kind::text::providerkind"
    )
    op.execute("DROP TYPE providerkind_old CASCADE")
