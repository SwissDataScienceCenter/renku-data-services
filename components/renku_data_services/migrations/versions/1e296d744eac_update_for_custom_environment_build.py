"""Update for custom environment build

Revision ID: 1e296d744eac
Revises: 64edf7ac0de0
Create Date: 2025-02-03 23:09:31.954635

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "1e296d744eac"
down_revision = "64edf7ac0de0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "build_parameters",
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("repository", sa.String(length=500), nullable=False),
        sa.Column("builder_variant", sa.String(length=99), nullable=False),
        sa.Column("frontend_variant", sa.String(length=99), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="sessions",
    )

    op.execute("CREATE TYPE environmentimagesource AS ENUM ('image', 'build')")

    op.add_column(
        "environments",
        sa.Column(
            "environment_image_source",
            sa.Enum("image", "build", name="environmentimagesource"),
            nullable=False,
            server_default="image",
        ),
        schema="sessions",
    )
    op.add_column(
        "environments",
        sa.Column("build_parameters_id", sa.String(length=26), nullable=True, server_default=None),
        schema="sessions",
    )
    op.create_foreign_key(
        "environments_build_parameters_id_fk",
        "environments",
        "build_parameters",
        ["build_parameters_id"],
        ["id"],
        ondelete="CASCADE",
        source_schema="sessions",
        referent_schema="sessions",
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint("environments_build_parameters_id_fk", "environments", schema="sessions", type_="foreignkey")
    op.drop_column("environments", "build_parameters_id", schema="sessions")
    op.drop_column("environments", "environment_image_source", schema="sessions")

    op.execute("DROP TYPE environmentimagesource")

    op.drop_table("build_parameters", schema="sessions")
    # ### end Alembic commands ###
