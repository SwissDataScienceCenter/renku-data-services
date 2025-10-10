"""migrate copied custom environments to make them copies

Revision ID: 75c83dd9d619
Revises: 450ae3930996
Create Date: 2025-02-18 10:17:45.657261

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "75c83dd9d619"
down_revision = "450ae3930996"
branch_labels = None
depends_on = None


def upgrade() -> None:
    col_names = [
        "name",
        "created_by_id",
        "description",
        "container_image",
        "default_url",
        "port",
        "working_directory",
        "mount_directory",
        "uid",
        "gid",
        "environment_kind",
        "args",
        "command",
        "creation_date",
        "is_archived ",
    ]
    col_names_pure = ", ".join(col_names)
    col_names_w_prefix = ", ".join(["sessions.environments." + col_name for col_name in col_names])

    all_duplicate_env_ids_query = (
        "SELECT sessions.launchers.environment_id "
        "FROM sessions.launchers "
        "INNER JOIN sessions.environments ON sessions.environments.id = sessions.launchers.environment_id "
        "WHERE sessions.environments.environment_kind = 'CUSTOM' "
        "GROUP BY sessions.launchers.environment_id "
        "HAVING COUNT(*) > 1 "
    )

    # NOTE: The two queries that are injected into one another here are fully hardcoded. So to avoid
    # having one really long string we disable bandit query injection for the two lines below.
    # NOTE: We want to make copies of the environments for N-1 launchers if the total number including
    # duplicates is N - row_num below enumerates the duplicates in each launcher/environment group.
    enumerated_duplicate_launchers = (
        "SELECT sessions.launchers.id, sessions.launchers.environment_id, "
        "row_number() OVER (PARTITION BY sessions.launchers.environment_id ORDER BY sessions.launchers.id) AS row_num "
        "FROM sessions.launchers "
        f"WHERE sessions.launchers.environment_id IN ({all_duplicate_env_ids_query}) "  # nosec B608
        "ORDER BY sessions.launchers.environment_id, sessions.launchers.id "
    )
    launcher_ids_to_decouple = f"SELECT a.id FROM ({enumerated_duplicate_launchers}) a WHERE a.row_num > 1 "  # nosec B608

    # Add temporary column in the environments table to store session launcher ids
    op.add_column(
        "environments",
        sa.Column("tmp_launcher_id", sa.VARCHAR(length=30), autoincrement=False, nullable=True),
        schema="sessions",
    )
    # Make copies of the environments
    op.execute(
        sa.text(
            f"INSERT INTO sessions.environments(id, tmp_launcher_id, {col_names_pure}) "
            + f"SELECT generate_ulid(), sessions.launchers.id, {col_names_w_prefix} "
            + "FROM sessions.environments "
            + "INNER JOIN sessions.launchers ON sessions.launchers.environment_id = sessions.environments.id "
            + f"WHERE sessions.launchers.id IN ({launcher_ids_to_decouple}) "
        )
    )
    # Update the session launchers to use the copied environments
    op.execute(
        sa.text(
            "UPDATE sessions.launchers "
            + "SET environment_id = sessions.environments.id "
            + "FROM sessions.environments "
            + "WHERE sessions.launchers.id = sessions.environments.tmp_launcher_id "
            + "AND sessions.environments.tmp_launcher_id IS NOT NULL "
        )
    )
    # Update the environments created_by_id field to be the same as the project
    op.execute(
        sa.text(
            "UPDATE sessions.environments envs "
            + "SET created_by_id = prjs.created_by_id "
            + "FROM sessions.launchers ls "
            + "INNER JOIN projects.projects prjs ON ls.project_id = prjs.id "
            + "WHERE envs.id = ls.environment_id "
            + "AND envs.tmp_launcher_id IS NOT NULL"
        )
    )
    # Drop the temporary column from environments
    op.drop_column("environments", "tmp_launcher_id", schema="sessions")


def downgrade() -> None:
    # NOTE: This just moves and copies data in the DB to fix a bug. So there is no
    # need to code the downgrade.
    pass
