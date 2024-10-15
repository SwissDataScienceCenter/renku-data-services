"""change serial to generated identity for primary keys

Revision ID: 8cc47fcf333b
Revises: 46236d8d7cbe
Create Date: 2024-10-15 09:33:04.868849

"""

import sqlalchemy as sa
from alembic import op
from psycopg import sql

# revision identifiers, used by Alembic.
revision = "8cc47fcf333b"
down_revision = "46236d8d7cbe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    connection = op.get_bind()
    tables = [
        ("users", "user_preferences", "id"),
        ("users", "users", "id"),
        ("users", "last_keycloak_event_timestamp", "id"),
        ("projects", "projects_repositories", "id"),
        ("common", "entity_slugs", "id"),
        ("common", "entity_slugs_old", "id"),
        ("resource_pools", "users", "id"),
        ("resource_pools", "resource_classes", "id"),
        ("resource_pools", "resource_pools", "id"),
        ("resource_pools", "tolerations", "id"),
        ("resource_pools", "node_affinities", "id"),
        ("events", "events", "id"),
        ("authz", "project_user_authz", "id"),
    ]

    for schema, table, column in tables:
        full_name = sql.Identifier(schema, table)
        statement = sql.SQL("SELECT MAX(id) FROM {}").format(full_name).as_string(connection)  # type: ignore[arg-type]
        res = connection.exec_driver_sql(statement)
        row = res.fetchone()
        next_id = 1
        if row is not None and len(row) > 0 and row[0] is not None:
            next_id = row[0] + 1

        statement = sa.sql.text(f"select pg_get_serial_sequence('{schema}.{table}', '{column}')")
        res = connection.execute(statement)
        row = res.fetchone()
        statement = sa.sql.text(
            f"""
              ALTER TABLE {schema}.{table}
                  ALTER COLUMN {column} DROP DEFAULT;
            """
        )
        connection.execute(statement)
        if row is not None and len(row) > 0 and row[0] is not None:
            sequence_name = row[0]
            statement = sa.sql.text(f"DROP SEQUENCE {sequence_name}")
            connection.execute(statement)

        statement = sa.sql.text(
            f"""
              ALTER TABLE {schema}.{table}
                  ALTER COLUMN {column} SET DATA TYPE bigint,
                  ALTER COLUMN {column} ADD GENERATED ALWAYS AS IDENTITY (START WITH {next_id});   
            """
        )
        connection.execute(statement)

    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    pass
    # ### end Alembic commands ###
