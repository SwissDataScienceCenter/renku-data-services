"""squashme: add connected services

Revision ID: 1dd7c321f126
Revises: aa58a844784d
Create Date: 2024-04-22 12:43:18.016567

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '1dd7c321f126'
down_revision = 'aa58a844784d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('oauth2_clients', sa.Column('client_secret', sa.String(length=500), nullable=True), schema='connected_services')
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('oauth2_clients', 'client_secret', schema='connected_services')
    # ### end Alembic commands ###