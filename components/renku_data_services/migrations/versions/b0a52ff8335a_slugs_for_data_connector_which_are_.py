"""slugs for data connector which are owned by projects

Revision ID: b0a52ff8335a
Revises: 483af0d70cf4
Create Date: 2025-01-22 16:38:57.220486

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "b0a52ff8335a"
down_revision = "483af0d70cf4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index("entity_slugs_unique_slugs", table_name="entity_slugs", schema="common")
    op.create_index(
        "entity_slugs_unique_slugs",
        "entity_slugs",
        ["namespace_id", "project_id", "data_connector_id", "slug"],
        unique=True,
        schema="common",
        postgresql_nulls_not_distinct=True,
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(
        "entity_slugs_unique_slugs", table_name="entity_slugs", schema="common", postgresql_nulls_not_distinct=True
    )
    op.create_index("entity_slugs_unique_slugs", "entity_slugs", ["namespace_id", "slug"], unique=True, schema="common")
    # ### end Alembic commands ###
