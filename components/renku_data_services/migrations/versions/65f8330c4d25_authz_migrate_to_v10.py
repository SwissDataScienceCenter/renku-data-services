"""authz: migrate to v10

Revision ID: 65f8330c4d25
Revises: cd424c01676e
Create Date: 2026-04-21 17:22:21.640693

"""

from renku_data_services.app_config import logging
from renku_data_services.authz.config import AuthzConfig
from renku_data_services.authz.schemas import v10

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision = "65f8330c4d25"
down_revision = "cd424c01676e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    config = AuthzConfig.from_env()
    client = config.authz_client()
    responses = v10.upgrade(client)
    logger.info(f"Upgraded Authzed schema to v10: {responses}")


def downgrade() -> None:
    config = AuthzConfig.from_env()
    client = config.authz_client()
    responses = v10.downgrade(client)
    logger.info(f"Downgraded Authzed schema from v10: {responses}")
