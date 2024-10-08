"""add authorization for data connectors

Revision ID: 5335b8548c79
Revises: 3cf2adf9896b
Create Date: 2024-09-12 13:11:11.087316

"""

import logging

import sqlalchemy as sa
from alembic import op

from renku_data_services.authz.config import AuthzConfig
from renku_data_services.authz.schemas import generate_v4

# revision identifiers, used by Alembic.
revision = "5335b8548c79"
down_revision = "3cf2adf9896b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    config = AuthzConfig.from_env()
    client = config.authz_client()
    connection = op.get_bind()
    with connection.begin_nested() as tx:
        op.execute(sa.text("LOCK TABLE projects.projects IN EXCLUSIVE MODE"))
        stmt = (
            sa.select(sa.column("id", type_=sa.VARCHAR))
            .select_from(sa.table("projects", schema="projects"))
            .where(sa.column("visibility") == sa.literal("public", type_=sa.Enum("visibility")))
        )
        project_ids = connection.scalars(stmt).all()
        v4 = generate_v4(project_ids)
        responses = v4.upgrade(client)
        tx.commit()
        logging.info(
            f"Finished upgrading the Authz schema to version 4 in Alembic revision {revision}, response: {responses}"
        )


def downgrade() -> None:
    config = AuthzConfig.from_env()
    client = config.authz_client()
    connection = op.get_bind()
    with connection.begin_nested() as tx:
        op.execute(sa.text("LOCK TABLE projects.projects IN EXCLUSIVE MODE"))
        stmt = (
            sa.select(sa.column("id", type_=sa.VARCHAR))
            .select_from(sa.table("projects", schema="projects"))
            .where(sa.column("visibility") == sa.literal("public", type_=sa.Enum("visibility")))
        )
        project_ids = connection.scalars(stmt).all()
        v4 = generate_v4(project_ids)
        responses = v4.downgrade(client)
        tx.commit()
        logging.info(
            f"Finished downgrading the Authz schema from version 4 in Alembic revision {revision}, response: {responses}"
        )
