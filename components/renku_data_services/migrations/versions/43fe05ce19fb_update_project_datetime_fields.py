"""update project datetime fields

Revision ID: 43fe05ce19fb
Revises: 89aa4573cfa9
Create Date: 2024-04-17 08:46:42.560657

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '43fe05ce19fb'
down_revision = '89aa4573cfa9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('projects', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True), schema='projects')
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('projects', 'updated_at', schema='projects')
    # ### end Alembic commands ###