"""authz add groups and namespaces in schema

Revision ID: f6203f71982a
Revises: 7e5edc3b84b9
Create Date: 2024-05-09 18:14:51.256194

"""

import logging

from authzed.api.v1 import ReadSchemaRequest, WriteSchemaRequest  # type: ignore[attr-defined]
from grpc import RpcError

from renku_data_services.authz.config import AuthzConfig
from renku_data_services.authz.schemas import v2

# revision identifiers, used by Alembic.
revision = "f6203f71982a"
down_revision = "7e5edc3b84b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    config = AuthzConfig.from_env()
    client = config.authz_client()
    existing_schema = client.ReadSchema(ReadSchemaRequest())

    try:
        existing_schema = client.ReadSchema(ReadSchemaRequest())
        if "definition group" in existing_schema.schema_text:
            logging.info(f"Skipping {revision}, as Authz is likely already populated.")
            return
    except RpcError:
        pass

    res = client.WriteSchema(WriteSchemaRequest(schema=v2))
    logging.info(
        f"Finished adding groups and namespaces to Authz schema migration, revision {revision}, response: {res}"
    )


def downgrade() -> None:
    # Question for the PR reviewer: Should we implement up and down migrations for authz DB?
    # If yes then here we would have to remove all relations for groups and namespaces and then remove or edit the schema
    pass
