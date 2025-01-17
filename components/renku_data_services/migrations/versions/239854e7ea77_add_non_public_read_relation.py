"""Add non-public-read relation

Revision ID: 239854e7ea77
Revises: d71f0f795d30
Create Date: 2025-01-17 14:34:47.305393

"""

import logging

from renku_data_services.authz.config import AuthzConfig
from renku_data_services.authz.schemas import v5

# revision identifiers, used by Alembic.
revision = "239854e7ea77"
down_revision = "75c83dd9d619"
branch_labels = None
depends_on = None


def upgrade() -> None:
    config = AuthzConfig.from_env()
    client = config.authz_client()
    responses = v5.upgrade(client)
    logging.info(
        f"Finished upgrading the Authz schema to version 5 in Alembic revision {revision}, response: {responses}"
    )


def downgrade() -> None:
    config = AuthzConfig.from_env()
    client = config.authz_client()
    responses = v5.downgrade(client)
    logging.info(
        f"Finished downgrading the Authz schema from version 5 in Alembic revision {revision}, response: {responses}"
    )
