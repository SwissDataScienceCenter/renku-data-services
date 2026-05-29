"""upgrade authzed schema to v11

Revision ID: f2d4841e924b
Revises: 65f8330c4d25
Create Date: 2026-05-27 14:32:12.144808

"""

from renku_data_services.app_config import logging
from renku_data_services.authz.config import AuthzConfig
from renku_data_services.authz.schemas import v11

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision = "f2d4841e924b"
down_revision = "65f8330c4d25"
branch_labels = None
depends_on = None


def upgrade() -> None:
    config = AuthzConfig.from_env()
    client = config.authz_client()
    responses = v11.upgrade(client)
    logger.info(
        f"Finished upgrading the Authz schema to version 11 in Alembic revision {revision}, response: {responses}"
    )


def downgrade() -> None:
    config = AuthzConfig.from_env()
    client = config.authz_client()
    responses = v11.downgrade(client)
    logger.info(
        f"Finished downgrading the Authz schema from version 11 in Alembic revision {revision}, response: {responses}"
    )
