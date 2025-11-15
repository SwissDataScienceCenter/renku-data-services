"""Helper functions for writing migrations."""

from alembic import op
from psycopg import sql


def get_enum_values(enum_type: str) -> list[str]:
    """Return all values for the given enum type."""
    connection = op.get_bind()
    ident = sql.Identifier(enum_type)
    statement = (
        sql.SQL("select unnest(enum_range(null::{}))").format(ident).as_string(connection)  # type: ignore[arg-type]
    )
    result = connection.exec_driver_sql(statement)
    rows = result.all()
    return [v[0] for v in rows]


def create_enum_type(enum_type: str, values: list[str]) -> None:
    """Creates a new enum type."""
    value_list = ", ".join([f"'{e}'" for e in values])
    op.execute(f"CREATE TYPE {enum_type} AS ENUM ({value_list})")
