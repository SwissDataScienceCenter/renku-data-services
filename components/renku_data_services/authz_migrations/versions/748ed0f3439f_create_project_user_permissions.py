"""create project-user permissions

Revision ID: 748ed0f3439f
Revises:
Create Date: 2023-11-13 13:59:12.707850

"""
from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "748ed0f3439f"
down_revision: str | None = None
branch_labels = ('authz',)
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "project_user_authz",
        sa.Column("project_id", sa.String(length=26), nullable=False),
        sa.Column("role", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="authz",
    )
    op.create_index(
        op.f("ix_authz_project_user_authz_project_id"),
        "project_user_authz",
        ["project_id"],
        unique=False,
        schema="authz",
    )
    op.create_index(
        op.f("ix_authz_project_user_authz_role"), "project_user_authz", ["role"], unique=False, schema="authz"
    )
    op.create_index(
        op.f("ix_authz_project_user_authz_user_id"), "project_user_authz", ["user_id"], unique=False, schema="authz"
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_authz_project_user_authz_user_id"), table_name="project_user_authz", schema="authz")
    op.drop_index(op.f("ix_authz_project_user_authz_role"), table_name="project_user_authz", schema="authz")
    op.drop_index(op.f("ix_authz_project_user_authz_project_id"), table_name="project_user_authz", schema="authz")
    op.drop_table("project_user_authz", schema="authz")
    # ### end Alembic commands ###
