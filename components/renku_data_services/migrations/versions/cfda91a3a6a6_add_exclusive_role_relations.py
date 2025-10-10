"""Add exclusive role relations

Revision ID: cfda91a3a6a6
Revises: f4ad62b7b323
Create Date: 2025-06-13 16:06:26.421053

"""

from renku_data_services.app_config import logging
from renku_data_services.authz.config import AuthzConfig
from renku_data_services.authz.schemas import v7

# revision identifiers, used by Alembic.
revision = "cfda91a3a6a6"
down_revision = "f4ad62b7b323"
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)


def upgrade() -> None:
    config = AuthzConfig.from_env()
    client = config.authz_client()
    responses = v7.upgrade(client)
    logger.info(
        f"Finished upgrading the Authz schema to version 7 in Alembic revision {revision}, response: {responses}"
    )


def downgrade() -> None:
    config = AuthzConfig.from_env()
    client = config.authz_client()
    responses = v7.downgrade(client)
    logger.info(
        f"Finished downgrading the Authz schema from version 7 in Alembic revision {revision}, response: {responses}"
    )
