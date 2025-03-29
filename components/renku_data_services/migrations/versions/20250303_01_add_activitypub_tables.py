"""Add ActivityPub tables.

Revision ID: 20250303_01
Revises: fd2117d2be29
Create Date: 2025-03-03 13:52:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from renku_data_services.utils.sqlalchemy import ULIDType


# revision identifiers, used by Alembic.
revision = "20250303_01"
down_revision = "fd2117d2be29"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade database schema."""
    # Create activitypub schema
    op.execute("CREATE SCHEMA IF NOT EXISTS activitypub")

    # Create actors table
    op.create_table(
        "actors",
        sa.Column("id", ULIDType, primary_key=True),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("user_id", sa.String, sa.ForeignKey("users.users.keycloak_id", ondelete="CASCADE"), nullable=True),
        sa.Column("project_id", ULIDType, sa.ForeignKey("projects.projects.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column("private_key_pem", sa.Text, nullable=True),
        sa.Column("public_key_pem", sa.Text, nullable=True),
        schema="activitypub",
    )
    op.create_index("ix_actors_username", "actors", ["username"], unique=True, schema="activitypub")
    op.create_index("ix_actors_user_id", "actors", ["user_id"], schema="activitypub")
    op.create_index("ix_actors_project_id", "actors", ["project_id"], schema="activitypub")

    # Create followers table
    op.create_table(
        "followers",
        sa.Column("id", ULIDType, primary_key=True),
        sa.Column("actor_id", ULIDType, sa.ForeignKey("activitypub.actors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("follower_actor_uri", sa.String(2048), nullable=False),
        sa.Column("accepted", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        schema="activitypub",
    )
    op.create_index("ix_followers_actor_id", "followers", ["actor_id"], schema="activitypub")
    op.create_index(
        "ix_followers_actor_id_follower_actor_uri",
        "followers",
        ["actor_id", "follower_actor_uri"],
        unique=True,
        schema="activitypub",
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_table("followers", schema="activitypub")
    op.drop_table("actors", schema="activitypub")
    op.execute("DROP SCHEMA IF EXISTS activitypub")
