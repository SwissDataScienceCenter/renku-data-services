"""upgrade oauth provider kind enum

Revision ID: 58ad5426c2f3
Revises: 287879848fb3
Create Date: 2026-01-14 14:35:29.539830

"""

from alembic import op
from sqlalchemy.exc import OperationalError

from renku_data_services.app_config import logging

# revision identifiers, used by Alembic.
revision = "58ad5426c2f3"
down_revision = "287879848fb3"
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)

# NOTE: Postgres does not allow removing values from an enum


def upgrade() -> None:
    connection = op.get_bind()
    with connection.begin_nested() as tx:
        try:
            op.execute("DELETE FROM connected_services.oauth2_clients WHERE kind = 'drive'")
            op.execute("DELETE FROM connected_services.oauth2_clients WHERE kind = 'onedrive'")
            tx.commit()
        except OperationalError as err:
            logger.debug(f"Skipped DELETE section from migration of the connected_services.oauth2_clients table: {err}")
            tx.rollback()
    op.execute("ALTER TYPE providerkind RENAME TO providerkind_old")
    op.execute("CREATE TYPE providerkind AS ENUM ('dropbox', 'generic_oidc', 'github', 'gitlab', 'google')")
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
