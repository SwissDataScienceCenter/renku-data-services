"""authz add initial schema

Revision ID: ce1a111d6694
Revises: 89aa4573cfa9
Create Date: 2024-04-11 09:05:15.645542

"""

import logging

from renku_data_services.authz.config import AuthzConfig
from renku_data_services.authz.schemas import v1

# revision identifiers, used by Alembic.
revision = "ce1a111d6694"
down_revision = "89aa4573cfa9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    config = AuthzConfig.from_env()
    client = config.authz_client()
    responses = v1.upgrade(client)
    logging.info(
        f"Finished upgrading the Authz schema to version 1 in Alembic revision {revision}, response: {responses}"
    )


def downgrade() -> None:
    config = AuthzConfig.from_env()
    client = config.authz_client()
    responses = v1.downgrade(client)
    logging.info(
        f"Finished downgrading the Authz schema from version 1 in Alembic revision {revision}, response: {responses}"
    )
