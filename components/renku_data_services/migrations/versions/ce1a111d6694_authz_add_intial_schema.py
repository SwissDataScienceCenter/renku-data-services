"""authz add intial schema

Revision ID: ce1a111d6694
Revises: 89aa4573cfa9
Create Date: 2024-04-11 09:05:15.645542

"""
import logging

from authzed.api.v1 import WriteSchemaRequest  # type: ignore[attr-defined]

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
    res = client.WriteSchema(WriteSchemaRequest(schema=v1))
    logging.info(f"Finished initial Authz schema migration, revision {revision}, response: {res}")

async def downgrade() -> None:
    pass
