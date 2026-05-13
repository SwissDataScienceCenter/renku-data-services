"""Update resource usage query

Revision ID: d785165cf8cd
Revises: cd424c01676e
Create Date: 2026-05-11 12:22:10.151949

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "d785165cf8cd"
down_revision = "cd424c01676e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    -- This corrects the interval for:
    -- - breaks in observations > 10mins when the service was down or slow - in this case we only charge for 10 mins of the recording
    -- - breaks in observations < 10mins when the service was restarting often in - in this case we charge for the correct amount - i.e. difference in observation dates
    -- - if we cannnot find the next observation date we assume things ran for 10mins (the capture_interval)
    -- NOTE: The capture_interval is a configuration value, currently set at 10mins, that is why the explanation uses 10mins
    -- NOTE: least function below ignores NULL
    create or replace view "resource_pools"."resource_requests_view_v2" as
    select
        *,
        least(lead(capture_date) over (partition by uid, phase order by capture_date) - capture_date, capture_interval) as corrected_interval
    from
        resource_pools.resource_requests_log;
    """)


def downgrade() -> None:
    op.execute('drop view if exists "resource_pools"."resource_requests_view_v2"')
