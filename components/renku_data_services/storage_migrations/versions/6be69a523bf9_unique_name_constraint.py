"""unique name constraint

Revision ID: 6be69a523bf9
Revises: 18d11d77ff15
Create Date: 2023-08-31 07:01:25.113476

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "6be69a523bf9"
down_revision = "18d11d77ff15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_unique_constraint("_unique_name_uc", "cloud_storage", ["project_id", "name"], schema="storage")
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint("_unique_name_uc", "cloud_storage", schema="storage", type_="unique")
    # ### end Alembic commands ###
