"""fix user preferences sequence

Revision ID: 46236d8d7cbe
Revises: 726d5d0e1f28
Create Date: 2024-10-15 07:42:08.683052

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "46236d8d7cbe"
down_revision = "88af2fdd2cc7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    connection = op.get_bind()
    op.execute(sa.text("LOCK TABLE users.user_preferences IN EXCLUSIVE MODE"))
    last_id_stmt = sa.select(sa.func.max(sa.column("id", type_=sa.INT))).select_from(
        sa.table("user_preferences", schema="users")
    )
    last_id = connection.scalars(last_id_stmt).one_or_none()
    if last_id is None or last_id <= 0:
        return
    op.execute(sa.text(f"ALTER SEQUENCE users.user_preferences_id_seq RESTART WITH {last_id + 1}"))

    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    pass
    # ### end Alembic commands ###
