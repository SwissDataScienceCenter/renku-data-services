"""authz add groups and namespaces in schema

Revision ID: f6203f71982a
Revises: 7e5edc3b84b9
Create Date: 2024-05-09 18:14:51.256194

"""

from renku_data_services.app_config import logging
from renku_data_services.authz.config import AuthzConfig
from renku_data_services.authz.schemas import v2

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision = "f6203f71982a"
down_revision = "7e5edc3b84b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    config = AuthzConfig.from_env()
    client = config.authz_client()
    responses = v2.upgrade(client)
    logger.info(
        f"Finished upgrading the Authz schema to version 2 in Alembic revision {revision}, response: {responses}"
    )


def downgrade() -> None:
    config = AuthzConfig.from_env()
    client = config.authz_client()
    responses = v2.downgrade(client)
    logger.info(
        f"Finished downgrading the Authz schema from version 2 in Alembic revision {revision}, response: {responses}"
    )
