"""Update events sync table

Revision ID: cc3b595b7423
Revises: a8f0e7b3c2d1
Create Date: 2026-06-01 09:16:03.862495

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "cc3b595b7423"
down_revision = "a8f0e7b3c2d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("last_keycloak_event_timestamp", schema="users")
    op.create_table(
        "last_keycloak_event_timestamp_v2",
        sa.Column(
            "id",
            sa.Enum("realm_events", "realm_admin_events", name="keycloakeventsource", create_type=True),
            nullable=False,
        ),
        sa.Column("timestamp_utc", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="users",
    )


def downgrade() -> None:
    op.drop_table("last_keycloak_event_timestamp_v2", schema="users")
    op.execute("DROP TYPE keycloakeventsource")
    op.create_table(
        "last_keycloak_event_timestamp",
        sa.Column(
            "id",
            sa.INTEGER(),
            sa.Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=2147483647, cycle=False, cache=1),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("timestamp_utc", postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
        sa.PrimaryKeyConstraint("id", name="last_keycloak_event_timestamp_pkey"),
        schema="users",
    )
