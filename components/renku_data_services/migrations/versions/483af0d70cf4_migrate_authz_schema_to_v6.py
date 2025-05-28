"""Migrate authz schema to v6

Revision ID: 559b1fc46cfe
Revises: 71ef5efe740f
Create Date: 2025-01-22 10:37:40.218992

"""

from renku_data_services.app_config import logging
from renku_data_services.authz.config import AuthzConfig
from renku_data_services.authz.schemas import v6

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision = "483af0d70cf4"
down_revision = "559b1fc46cfe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    config = AuthzConfig.from_env()
    client = config.authz_client()
    responses = v6.upgrade(client)
    logger.info(
        f"Finished upgrading the Authz schema to version 6 in Alembic revision {revision}, response: {responses}"
    )


def downgrade() -> None:
    config = AuthzConfig.from_env()
    client = config.authz_client()
    responses = v6.downgrade(client)
    logger.info(
        f"Finished downgrading the Authz schema from version 6 in Alembic revision {revision}, response: {responses}"
    )
