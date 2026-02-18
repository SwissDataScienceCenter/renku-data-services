"""create resource_usage table

Revision ID: c6af6a1088f1
Revises: 9b18adb58e63
Create Date: 2026-01-20 16:58:55.442236

"""

import sqlalchemy as sa
from alembic import op

from renku_data_services.utils.sqlalchemy import ComputeCapacityType, CreditType, DataSizeType, ULIDType

# revision identifiers, used by Alembic.
revision = "c6af6a1088f1"
down_revision = "287879848fb3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_resource_class_costs()
    create_resource_requests_log()
    create_resource_requests_view()
    create_resource_requests_limits()


def downgrade() -> None:
    op.execute("drop view resource_pools.resource_requests_view")
    op.drop_table("resource_requests_log", schema="resource_pools")
    op.drop_table("resource_requests_limits", schema="resource_pools")
    op.drop_table("resource_class_costs", schema="resource_pools")


def create_resource_class_costs() -> None:
    op.create_table(
        "resource_class_costs",
        sa.Column("resource_class_id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("cost", CreditType(), nullable=False),
        schema="resource_pools",
    )
    op.execute("""
    alter table "resource_pools"."resource_class_costs"
    add constraint "fk_resource_class_costs_resource_class_id"
    foreign key ("resource_class_id")
    references "resource_pools"."resource_classes"("id")
    on delete cascade
    """)


def create_resource_requests_limits() -> None:
    op.create_table(
        "resource_requests_limits",
        sa.Column("resource_pool_id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("total_limit", CreditType(), nullable=False),
        sa.Column("user_limit", CreditType(), nullable=False),
        schema="resource_pools",
    )
    op.create_foreign_key(
        "fk_resource_requests_limits_resource_pool_id",
        source_table="resource_requests_limits",
        referent_table="resource_pools",
        local_cols=["resource_pool_id"],
        remote_cols=["id"],
        referent_schema="resource_pools",
        source_schema="resource_pools",
        ondelete="cascade",
    )


def create_resource_requests_log() -> None:
    op.create_table(
        "resource_requests_log",
        sa.Column("id", ULIDType(), server_default=sa.text("generate_ulid()"), nullable=False),
        sa.Column("cluster_id", sa.String(), nullable=True),
        sa.Column("namespace", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("uid", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("api_version", sa.String(), nullable=False),
        sa.Column("phase", sa.String(), nullable=False),
        sa.Column("capture_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capture_interval", sa.Interval(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("project_id", ULIDType(), nullable=True),
        sa.Column("launcher_id", ULIDType(), nullable=True),
        sa.Column("resource_class_id", sa.Integer(), nullable=True),
        sa.Column("resource_class_cost", CreditType(), nullable=True),
        sa.Column("resource_pool_id", sa.Integer(), nullable=True),
        sa.Column("since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cpu_request", ComputeCapacityType(), nullable=True),
        sa.Column("memory_request", DataSizeType(), nullable=True),
        sa.Column("gpu_request", ComputeCapacityType(), nullable=True),
        sa.Column("gpu_slice", sa.Float(), nullable=True),
        sa.Column("gpu_product", sa.String(), nullable=True),
        sa.Column("disk_request", DataSizeType(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema="resource_pools",
    )
    op.create_index(
        index_name=None,
        table_name="resource_requests_log",
        columns=["capture_date"],
        unique=False,
        schema="resource_pools",
    )


def create_resource_requests_view() -> None:
    op.execute("""
    create or replace view "resource_pools"."resource_requests_view" as
    with
      cpu_obs as (
        select id, capture_date, dense_rank() over (order by capture_date asc) as rn
        from resource_pools.resource_requests_log
        where cpu_request is not null and user_id is not null
      ),
      mem_obs as (
        select id, capture_date, dense_rank() over (order by capture_date asc) as rn
        from resource_pools.resource_requests_log
        where memory_request is not null and user_id is not null
      ),
      disk_obs as (
        select id, capture_date, dense_rank() over (order by capture_date asc) as rn
        from resource_pools.resource_requests_log
        where disk_request is not null and user_id is not null
      ),
      gpu_obs as (
        select id, capture_date, dense_rank() over (order by capture_date asc) as rn
        from resource_pools.resource_requests_log
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
          t.resource_class_cost,
          t.resource_pool_id,
          t.cpu_request,
          t.memory_request,
          t.disk_request,
          t.gpu_request,
          t.gpu_slice,
          t.gpu_product,
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
        from resource_pools.resource_requests_log t
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
        t.resource_class_cost,
        t.resource_pool_id,
        t.cpu_request,
        t.memory_request,
        t.disk_request,
        t.gpu_request,
        t.gpu_slice,
        t.gpu_product,
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
