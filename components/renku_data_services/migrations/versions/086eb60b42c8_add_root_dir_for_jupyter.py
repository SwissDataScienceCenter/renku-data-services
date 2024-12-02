"""add root dir for jupyter

Revision ID: 086eb60b42c8
Revises: 9df92d455b11
Create Date: 2024-11-25 20:51:42.182997

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

root_dir = "/home/jovyan/work"
original_args = [
    "/entrypoint.sh jupyter server --ServerApp.ip=0.0.0.0 --ServerApp.port=8888 --ServerApp.base_url=$RENKU_BASE_URL_PATH "
    '--ServerApp.token="" --ServerApp.password="" --ServerApp.allow_remote_access=true '
    "--ContentsManager.allow_hidden=true --ServerApp.allow_origin=*",
]
new_args = [f'{original_args[0]} --ServerApp.root_dir="{root_dir}"']


# revision identifiers, used by Alembic.
revision = "086eb60b42c8"
down_revision = "9df92d455b11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        # NOTE: There is no equality comparison for JSONB but you can check if one JSONB is
        # contained within another with the @> operator
        sa.text(
            "UPDATE sessions.environments SET args=:new_args WHERE args @> :old_args AND args <@ :old_args"
        ).bindparams(
            sa.bindparam("old_args", value=original_args, type_=JSONB),
            sa.bindparam("new_args", value=new_args, type_=JSONB),
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE sessions.environments SET args=:old_args WHERE args @> :new_args AND args <@ :new_args"
        ).bindparams(
            sa.bindparam("old_args", value=original_args, type_=JSONB),
            sa.bindparam("new_args", value=new_args, type_=JSONB),
        )
    )
