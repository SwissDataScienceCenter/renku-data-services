"""bootstrap initial global environments

Mainly used for CI deployments so they have a envs for testing.

Revision ID: 450ae3930996
Revises: d71f0f795d30
Create Date: 2025-02-07 02:34:53.408066

"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from renku_data_services.app_config import logging

logger = logging.getLogger(__name__)

JSONVariant = sa.JSON().with_variant(JSONB(), "postgresql")
# revision identifiers, used by Alembic.
revision = "450ae3930996"
down_revision = "d71f0f795d30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
