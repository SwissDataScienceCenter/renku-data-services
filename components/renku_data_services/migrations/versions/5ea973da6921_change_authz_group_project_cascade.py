"""Change authz group permissions to project permissions cascade

Revision ID: 5ea973da6921
Revises: 42049656cdb8
Create Date: 2025-11-13 12:54:35.208489

"""

from renku_data_services.app_config import logging
from renku_data_services.authz.config import AuthzConfig
from renku_data_services.authz.schemas import v8

# revision identifiers, used by Alembic.
revision = "5ea973da6921"
down_revision = "42049656cdb8"
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)


def upgrade() -> None:
    config = AuthzConfig.from_env()
    client = config.authz_client()
    responses = v8.upgrade(client)
    logger.info(
        f"Finished upgrading the Authz schema to version 8 in Alembic revision {revision}, response: {responses}"
    )


def downgrade() -> None:
    config = AuthzConfig.from_env()
    client = config.authz_client()
    responses = v8.downgrade(client)
    logger.info(
        f"Finished downgrading the Authz schema from version 8 in Alembic revision {revision}, response: {responses}"
    )
