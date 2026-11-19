"""feat: migrate old project storages

Revision ID: eb976e4ecf40
Revises: 9fbed1a9c79f
Create Date: 2026-11-19 12:29:52.689588

"""

import sqlalchemy as sa
from alembic import op

from renku_data_services.utils.sqlalchemy import ByteSizeType, PurePosixPathType, ULIDType

# revision identifiers, used by Alembic.
revision = "eb976e4ecf40"
down_revision = "9fbed1a9c79f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    old_storages_table = sa.Table(
        "project_storage",
        sa.MetaData(schema="storage"),
        sa.Column("id", ULIDType(), primary_key=True),
        sa.Column("project_id", ULIDType()),
        sa.Column("storage_class", sa.String()),
        sa.Column("size_limit", ByteSizeType()),
        sa.Column("target_path", PurePosixPathType()),
        sa.Column("created_by_id", sa.String()),
        sa.Column("creation_date", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    rp_table = sa.Table(
        "resource_pools",
        sa.MetaData(schema="resource_pools"),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(40)),
        sa.Column("default", sa.Boolean()),
        sa.Column("public", sa.Boolean()),
    )
    connection = op.get_bind()
    stmt = old_storages_table.select()
    res = connection.execute(stmt)
    old_storages = res.all()
    print(f"old storages {old_storages}")

    # Insert a new resource pool (works)
    # insert_result = connection.execute(
    #     rp_table.insert().values(
    #         name="Project storage migration pool",
    #         default=False,
    #         public=False,
    #     ).returning(rp_table)
    # )
    # new_rp = insert_result.one()
    # print(f"hello {new_rp}")

    pass


def downgrade() -> None:
    # NOTE: we cannot perform a "downgrade" operation for this migration.
    pass
