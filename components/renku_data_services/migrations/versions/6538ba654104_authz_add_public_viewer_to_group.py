"""authz add public_viewer to group

Revision ID: 6538ba654104
Revises: 57dfd69ea814
Create Date: 2024-06-21 07:24:30.067012

"""

import logging

from renku_data_services.authz.config import AuthzConfig
from renku_data_services.authz.schemas import v3

# revision identifiers, used by Alembic.
revision = "6538ba654104"
down_revision = "57dfd69ea814"
branch_labels = None
depends_on = None


def upgrade() -> None:
    config = AuthzConfig.from_env()
    client = config.authz_client()
    responses = v3.upgrade(client)
    logging.info(
        f"Finished upgrading the Authz schema to version 3 in Alembic revision {revision}, response: {responses}"
    )


def downgrade() -> None:
    config = AuthzConfig.from_env()
    client = config.authz_client()
    responses = v3.downgrade(client)
    logging.info(
        f"Finished downgrading the Authz schema from version 3 in Alembic revision {revision}, response: {responses}"
    )
