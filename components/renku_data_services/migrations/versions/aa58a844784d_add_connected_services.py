"""add connected services

Revision ID: aa58a844784d
Revises: 89aa4573cfa9
Create Date: 2024-04-22 09:33:12.554624

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'aa58a844784d'
down_revision = '89aa4573cfa9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('oauth2_clients',
    sa.Column('id', sa.String(length=99), nullable=False),
    sa.Column('client_id', sa.String(length=500), nullable=False),
    sa.Column('display_name', sa.String(length=99), nullable=False),
    sa.Column('created_by_id', sa.String(), nullable=False),
    sa.Column('creation_date', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='connected_services'
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('oauth2_clients', schema='connected_services')
    # ### end Alembic commands ###