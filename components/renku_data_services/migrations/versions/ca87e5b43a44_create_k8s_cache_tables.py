"""create k8s cache tables

Revision ID: ca87e5b43a44
Revises: a1f7f5fbec9a
Create Date: 2025-04-04 14:19:00.340544

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "ca87e5b43a44"
down_revision = "a1f7f5fbec9a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "k8s_objects",
        sa.Column("id", sa.String(26), server_default=sa.text("generate_ulid()"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("namespace", sa.String(), nullable=False),
        sa.Column("creation_date", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("manifest", postgresql.JSONB(), nullable=False),
        sa.Column("deleted", sa.Boolean(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("cluster", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="common",
    )
    op.create_index(op.f("ix_common_k8s_objects_cluster"), "k8s_objects", ["cluster"], unique=False, schema="common")
    op.create_index(op.f("ix_common_k8s_objects_deleted"), "k8s_objects", ["deleted"], unique=False, schema="common")
    op.create_index(op.f("ix_common_k8s_objects_kind"), "k8s_objects", ["kind"], unique=False, schema="common")
    op.create_index(op.f("ix_common_k8s_objects_name"), "k8s_objects", ["name"], unique=False, schema="common")
    op.create_index(
        op.f("ix_common_k8s_objects_namespace"), "k8s_objects", ["namespace"], unique=False, schema="common"
    )
    op.create_index(op.f("ix_common_k8s_objects_user_id"), "k8s_objects", ["user_id"], unique=False, schema="common")
    op.create_index(op.f("ix_common_k8s_objects_version"), "k8s_objects", ["version"], unique=False, schema="common")
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_common_k8s_objects_version"), table_name="k8s_objects", schema="common")
    op.drop_index(op.f("ix_common_k8s_objects_user_id"), table_name="k8s_objects", schema="common")
    op.drop_index(op.f("ix_common_k8s_objects_namespace"), table_name="k8s_objects", schema="common")
    op.drop_index(op.f("ix_common_k8s_objects_name"), table_name="k8s_objects", schema="common")
    op.drop_index(op.f("ix_common_k8s_objects_kind"), table_name="k8s_objects", schema="common")
    op.drop_index(op.f("ix_common_k8s_objects_deleted"), table_name="k8s_objects", schema="common")
    op.drop_index(op.f("ix_common_k8s_objects_cluster"), table_name="k8s_objects", schema="common")
    op.drop_table("k8s_objects", schema="common")
    # ### end Alembic commands ###
