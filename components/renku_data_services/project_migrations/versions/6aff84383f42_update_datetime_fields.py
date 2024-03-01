"""update datetime fields

Revision ID: e0ce196a6022
Revises: 7c08ed2fb79d
Create Date: 2024-03-01 12:33:51.068133

"""

import sqlalchemy as sa
from alembic import op

# TODO: squash with previous revision

# revision identifiers, used by Alembic.
revision = "6aff84383f42"
down_revision = "e0ce196a6022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column(
        "projects",
        column_name="creation_date",
        server_default=sa.text("now()"),
        schema="projects",
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column(
        "projects",
        column_name="creation_date",
        server_default=None,
        schema="projects",
    )
    # ### end Alembic commands ###
