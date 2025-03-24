"""create audit tables

Revision ID: 4fdd23ef602d
Revises: 559b1fc46cfe
Create Date: 2025-03-21 10:46:16.687230

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.dialects.postgresql.ext import ExcludeConstraint
from sqlalchemy.dialects.postgresql.json import JSONB

from renku_data_services.project.orm import ProjectORM
from renku_data_services.utils.sanic_pgaudit import versioning_manager

# revision identifiers, used by Alembic.
revision = "4fdd23ef602d"
down_revision = "559b1fc46cfe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # set up versioning manager tables
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute("""CREATE OR REPLACE FUNCTION jsonb_change_key_name(data jsonb, old_key text, new_key text)
RETURNS jsonb
IMMUTABLE
LANGUAGE sql
AS $$
    SELECT ('{'||string_agg(to_json(CASE WHEN key = old_key THEN new_key ELSE key END)||':'||value, ',')||'}')::jsonb
    FROM (
        SELECT *
        FROM jsonb_each(data)
    ) t;
$$;""")
    op.create_table(
        "transaction",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("native_transaction_id", sa.BigInteger),
        sa.Column("issued_at", sa.DateTime),
        sa.Column("client_addr", INET),
        sa.Column("actor_id", sa.Text(), nullable=True),
        ExcludeConstraint(
            (sa.Column("native_transaction_id"), "="),
            (
                sa.func.tsrange(
                    sa.Column("issued_at") - sa.text("INTERVAL '1 hour'"),
                    sa.Column("issued_at"),
                ),
                "&&",
            ),
            using="gist",
            name="transaction_unique_native_tx_id",
        ),
        schema="common",
    )
    op.create_table(
        "activity",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("schema_name", sa.Text),
        sa.Column("table_name", sa.Text),
        sa.Column("relid", sa.Integer),
        sa.Column("issued_at", sa.DateTime),
        sa.Column("native_transaction_id", sa.BigInteger, index=True),
        sa.Column("verb", sa.Text),
        sa.Column("old_data", JSONB, default={}, server_default="{}"),
        sa.Column("changed_data", JSONB, default={}, server_default="{}"),
        sa.Column("transaction_id", sa.BigInteger),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["common.transaction.id"],
        ),
        schema="common",
    )
    op.create_index(
        op.f("ix_activity_native_transaction_id"), "activity", ["native_transaction_id"], schema="common", unique=False
    )

    # set up versioning manager triggers
    versioning_manager.create_audit_table(None, op.get_bind())
    versioning_manager.create_operators(None, op.get_bind())

    # manually set up version tracking for projects
    # pgsql_audit does this automatically, but with an "table.after_create" trigger, so this doesn't work for
    # existing tables
    query = versioning_manager.build_audit_table_query(
        table=ProjectORM.__table__, exclude_columns=ProjectORM.__versioned__.get("exclude")
    )
    op.execute(query)


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_activity_native_transaction_id"), table_name="activity", schema="common")
    op.drop_table("activity", schema="common")
    op.drop_table("transaction", schema="common")
    # ### end Alembic commands ###
