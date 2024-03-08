"""merge heads

Revision ID: 076205b7f551
Revises: 9a58a998ab79, b6c2602737c9, a74b8146d405, db64cd09e601, 29a9eff96010, 3828af92ffbb
Create Date: 2024-03-08 10:39:20.616519

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '076205b7f551'
down_revision = ('9a58a998ab79', 'b6c2602737c9', 'a74b8146d405', 'db64cd09e601', '29a9eff96010', '3828af92ffbb')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
