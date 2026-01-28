"""create resource data view

Revision ID: ee31a5e627c7
Revises: c6af6a1088f1
Create Date: 2026-01-28 09:55:50.247650

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ee31a5e627c7'
down_revision = 'c6af6a1088f1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    create or replace view "common"."resource_requests_view" as
      with
      -- list cpu request with the corresponding time it was observed
      requests_diffs as (
        select
          cluster_id,
          namespace,
          name,
          uid,
          kind,
          phase,
          user_id,
          cpu_request,
          memory_request,
          disk_request,
          capture_date,
          lead(capture_date) over cpu_w as next_cpu_date , -- next observation date
          lag(capture_date) over cpu_w as prev_cpu_date ,  -- prev observation date
          lead(capture_date) over mem_w as next_mem_date,
          lag(capture_date) over mem_w as prev_mem_date,
          lead(capture_date) over disk_w as next_disk_date,
          lag(capture_date) over disk_w as prev_disk_date
        from common.resource_requests_log
        where user_id is not null
          and phase in ('Bound', 'Running')
          and (cpu_request > 0 or memory_request > 0 or disk_request > 0)
        window
           cpu_w as (partition by user_id, cpu_request order by capture_date asc),
           mem_w as (partition by user_id, memory_request order by capture_date asc),
           disk_w as (partition by user_id, disk_request order by capture_date asc)
      ),
      -- add the actual time the value is observed, using the previous interval
      -- for the last observation or a fallback
      final_requests_diffs as (
        select
          *,
          coalesce(
            next_cpu_date - capture_date, -- the interval
            capture_date - prev_cpu_date, -- use the previous if last occurence
            interval '10' minute          -- use this fallback if there is only one row
          ) as cpu_time_diff,
          coalesce(
            next_mem_date - capture_date,
            capture_date - prev_mem_date,
            interval '10' minute
          ) as mem_time_diff,
          coalesce(
            next_disk_date - capture_date,
            capture_date - prev_disk_date,
            interval '10' minute
          ) as disk_time_diff
        from requests_diffs
      )
    select * from final_requests_diffs
    """)


def downgrade() -> None:
    op.execute("drop view resource_requests_view")
