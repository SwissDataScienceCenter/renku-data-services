"""upgrade authzed schema to v10

Revision ID: f2d4841e924b
Revises: a8f0e7b3c2d1
Create Date: 2026-05-27 14:32:12.144808

"""

from renku_data_services.app_config import logging
from renku_data_services.authz.config import AuthzConfig
from renku_data_services.authz.schemas import v10

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision = "f2d4841e924b"
down_revision = "a8f0e7b3c2d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    config = AuthzConfig.from_env()
    client = config.authz_client()
    responses = v10.upgrade(client)
    logger.info(
        f"Finished upgrading the Authz schema to version 10 in Alembic revision {revision}, response: {responses}"
    )


def downgrade() -> None:
    config = AuthzConfig.from_env()
    client = config.authz_client()
    responses = v10.downgrade(client)
    logger.info(
        f"Finished downgrading the Authz schema from version 10 in Alembic revision {revision}, response: {responses}"
    )
