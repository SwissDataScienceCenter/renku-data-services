"""fix primary key sequences

Revision ID: 5403953f654f
Revises: 024b215f9a14
Create Date: 2023-10-28 13:23:45.947375

"""
import sqlalchemy as sa
from alembic import op
from psycopg import sql

# revision identifiers, used by Alembic.
revision = "5403953f654f"
down_revision = "024b215f9a14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    schema = "resource_pools"
    tables = inspector.get_table_names(schema)

    for table in tables:
        if table in ["alembic_version", "resource_pools_users"]:
            continue
        full_name = sql.Identifier(schema, table)
        statement = sql.SQL("SELECT MAX(id) FROM {}").format(full_name).as_string(connection)
        res = connection.exec_driver_sql(statement)
        row = res.fetchone()
        if row is not None and len(row) > 0 and row[0] is not None:
            last_id = row[0]
            sequence_name = sql.Identifier("resource_pools", f"{table}_id_seq")
            statement = (sql.SQL("ALTER SEQUENCE {} RESTART WITH ").format(sequence_name).as_string(connection)) + str(
                last_id
            )  # Could not figure out how to add this to a query with Alembic
            connection.exec_driver_sql(statement)


def downgrade() -> None:
    pass
