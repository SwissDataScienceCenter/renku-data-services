"""create resource data view

Revision ID: ee31a5e627c7
Revises: c6af6a1088f1
Create Date: 2026-01-28 09:55:50.247650

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "ee31a5e627c7"
down_revision = "c6af6a1088f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    create or replace view "common"."resource_requests_view" as
    with
      cpu_obs as (
        select id, capture_date, dense_rank() over (order by capture_date asc) as rn
        from common.resource_requests_log
        where cpu_request is not null and user_id is not null
      ),
      mem_obs as (
        select id, capture_date, dense_rank() over (order by capture_date asc) as rn
        from common.resource_requests_log
        where memory_request is not null and user_id is not null
      ),
      disk_obs as (
        select id, capture_date, dense_rank() over (order by capture_date asc) as rn
        from common.resource_requests_log
        where disk_request is not null and user_id is not null
      ),
      gpu_obs as (
        select id, capture_date, dense_rank() over (order by capture_date asc) as rn
        from common.resource_requests_log
        where gpu_request is not null and user_id is not null
      ),
      requests_diffs as (
        select
          t.id,
          t.cluster_id,
          t.namespace,
          t.name,
          t.uid,
          t.kind,
          t.api_version,
          t.phase,
          t.user_id,
          t.project_id,
          t.launcher_id,
          t.resource_class_id,
          t.resource_pool_id,
          t.cpu_request,
          t.memory_request,
          t.disk_request,
          t.gpu_request,
          t.gpu_slice,
          t.capture_date,
          t.capture_interval,
          -- cpu next capture date
          (select min(c.capture_date) from cpu_obs c where c.rn = cs.rn + 1) as cpu_next_date,
          -- memory next capture date
          (select min(c.capture_date) from mem_obs c where c.rn = ms.rn + 1) as mem_next_date,
          -- disk next capture date
          (select min(c.capture_date) from disk_obs c where c.rn = ds.rn + 1) as disk_next_date,
          -- gpu next capture date
          (select min(c.capture_date) from gpu_obs c where c.rn = gs.rn + 1) as gpu_next_date
        from common.resource_requests_log t
        left join cpu_obs cs on cs.id = t.id
        left join mem_obs ms on ms.id = t.id
        left join disk_obs ds on ds.id = t.id
        left join gpu_obs gs on gs.id = t.id
        where t.user_id is not null
          and t.phase in ('Running', 'Bound')
        order by t.capture_date asc
      )
      select
        t.id,
        t.cluster_id,
        t.namespace,
        t.name,
        t.uid,
        t.kind,
        t.api_version,
        t.phase,
        t.user_id,
        t.project_id,
        t.launcher_id,
        t.resource_class_id,
        t.resource_pool_id,
        t.cpu_request,
        t.memory_request,
        t.disk_request,
        t.gpu_request,
        t.gpu_slice,
        t.capture_date,
        t.capture_interval,
        case
          when t.cpu_request is null then null
          else least(t.cpu_next_date - t.capture_date, t.capture_interval)
        end as cpu_time,
        case
          when t.memory_request is null then null
          else least(t.mem_next_date - t.capture_date, t.capture_interval)
        end as mem_time,
        case
           when t.gpu_request is null then null
           else least(t.gpu_next_date - t.capture_date, t.capture_interval)
        end as gpu_time,
        case
           when t.disk_request is null then null
           else least(t.disk_next_date - t.capture_date, t.capture_interval)
        end as disk_time
      from requests_diffs t
    """)


def downgrade() -> None:
    op.execute("drop view resource_requests_view")
