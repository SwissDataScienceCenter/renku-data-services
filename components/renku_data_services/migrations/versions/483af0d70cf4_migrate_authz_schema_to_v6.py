"""Migrate authz schema to v6

Revision ID: 483af0d70cf4
Revises: 64edf7ac0de0

Create Date: 2025-01-22 10:37:40.218992

"""

import logging

from renku_data_services.authz.config import AuthzConfig
from renku_data_services.authz.schemas import v6

# revision identifiers, used by Alembic.
revision = "483af0d70cf4"
down_revision = "64edf7ac0de0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    config = AuthzConfig.from_env()
    client = config.authz_client()
    responses = v6.upgrade(client)
    logging.info(
        f"Finished upgrading the Authz schema to version 6 in Alembic revision {revision}, response: {responses}"
    )


def downgrade() -> None:
    config = AuthzConfig.from_env()
    client = config.authz_client()
    responses = v6.downgrade(client)
    logging.info(
        f"Finished downgrading the Authz schema from version 6 in Alembic revision {revision}, response: {responses}"
    )
