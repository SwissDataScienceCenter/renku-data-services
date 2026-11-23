"""feat: migrate old project storages

Revision ID: eb976e4ecf40
Revises: 9fbed1a9c79f
Create Date: 2026-11-19 12:29:52.689588

"""

from typing import Any

import sqlalchemy as sa
from alembic import op

from renku_data_services.base_models.bytesize import ByteSize
from renku_data_services.utils.sqlalchemy import ByteSizeType, PurePosixPathType, ULIDType

# revision identifiers, used by Alembic.
revision = "eb976e4ecf40"
down_revision = "9fbed1a9c79f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    old_storages_table = sa.Table(
        "project_storage",
        sa.MetaData(schema="storage"),
        sa.Column("id", ULIDType(), primary_key=True),
        sa.Column("project_id", ULIDType()),
        sa.Column("storage_class", sa.String()),
        sa.Column("size_limit", ByteSizeType()),
        sa.Column("target_path", PurePosixPathType()),
        sa.Column("created_by_id", sa.String()),
        sa.Column("creation_date", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )

    connection = op.get_bind()
    old_storages_stmt = old_storages_table.select()
    old_storages_res = connection.execute(old_storages_stmt)
    old_storages = old_storages_res.all()
    # Do nothing if there are no entries in the storage.project_storage database table.
    if not old_storages:
        return

    rp_table = sa.Table(
        "resource_pools",
        sa.MetaData(schema="resource_pools"),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(40)),
        sa.Column("default", sa.Boolean()),
        sa.Column("public", sa.Boolean()),
    )

    # Create the resource pool for the migrated storage
    rp_name = "Project storage migration pool"
    rp_stmt = (
        rp_table.select()
        .where(rp_table.c.name == rp_name)
        .where(rp_table.c.default == False)
        .where(rp_table.c.public == False)
    )
    rp_res = connection.execute(rp_stmt)
    resource_pool = rp_res.one_or_none()
    if resource_pool is None:
        insert_rp_stmt = (
            rp_table.insert()
            .values(
                name=rp_name,
                default=False,
                public=False,
            )
            .returning(rp_table)
        )
        insert_rp_result = connection.execute(insert_rp_stmt)
        resource_pool = insert_rp_result.one()

    sf_table = sa.Table(
        "storage_flavors",
        sa.MetaData(schema="resource_pools"),
        sa.Column("id", ULIDType(), primary_key=True),
        sa.Column("k8s_storage_class_name", sa.String()),
        sa.Column("display_name", sa.String()),
        sa.Column("min_size", ByteSizeType()),
        sa.Column("admin_documentation", sa.String()),
        sa.Column("documentation", sa.String()),
        sa.Column("creation_date", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    sq_table = sa.Table(
        "storage_quotas",
        sa.MetaData(schema="resource_pools"),
        sa.Column("id", ULIDType(), primary_key=True),
        sa.Column("resource_pool_id", sa.Integer()),
        sa.Column("storage_flavor_id", ULIDType()),
        sa.Column("total_size", ByteSizeType()),
        sa.Column("max_size", ByteSizeType()),
        sa.Column("creation_date", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    project_storages_v2_table = sa.Table(
        "project_storages_v2",
        sa.MetaData(schema="storage"),
        sa.Column("id", ULIDType(), primary_key=True),
        sa.Column("project_id", ULIDType()),
        sa.Column("storage_quota_id", ULIDType()),
        sa.Column("requested_size", ByteSizeType()),
        sa.Column("actual_size", ByteSizeType()),
        sa.Column("target_path", PurePosixPathType()),
        sa.Column("k8s_pvc_name", sa.String()),
        sa.Column("k8s_pvc_status", sa.String()),
        sa.Column("created_by_id", sa.String()),
        sa.Column("creation_date", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )

    storage_flavors = dict[str, Any]()
    storage_quotas = dict[str, Any]()
    for old_storage in old_storages:
        # Create the storage flavor for the migrated storage
        storage_flavor = storage_flavors.get(old_storage.storage_class)
        if storage_flavor is None:
            insert_sf_stmt = (
                sf_table.insert()
                .values(
                    k8s_storage_class_name=old_storage.storage_class,
                    display_name=f"Project storage migration: {old_storage.storage_class}",
                    min_size=ByteSize.from_gibi(2),  # NOTE: using 2GiB here to block usage of the migration quotas
                    admin_documentation="Storage flavor created to migrate old project storage.",
                )
                .returning(sf_table)
            )
            insert_sf_result = connection.execute(insert_sf_stmt)
            storage_flavor = insert_sf_result.one()
            storage_flavors[old_storage.storage_class] = storage_flavor

        # Create the storage quota for the migrated storage
        storage_quota = storage_quotas.get(str(storage_flavor.id))
        if storage_quota is None:
            insert_sq_stmt = (
                sq_table.insert()
                .values(
                    resource_pool_id=resource_pool.id,
                    storage_flavor_id=storage_flavor.id,
                    total_size=ByteSize.from_gibi(1),  # NOTE: using 1GiB here to block usage of the migration quotas
                    max_size=ByteSize.from_gibi(1),  # NOTE: using 1GiB here to block usage of the migration quotas
                )
                .returning(sq_table)
            )
            insert_sq_result = connection.execute(insert_sq_stmt)
            storage_quota = insert_sq_result.one()
            storage_quotas[str(storage_flavor.id)] = storage_quota

        # Create the new project storage for the migrated storage
        pvc_name = f"pv-{old_storage.project_id}-0".lower()  # NOTE: this should map to the correct PVC
        insert_storage_v2_stmt = (
            project_storages_v2_table.insert()
            .values(
                id=old_storage.id,  # NOTE: keep the ID of the project storage
                project_id=old_storage.project_id,
                storage_quota_id=storage_quota.id,
                requested_size=old_storage.size_limit,
                target_path=old_storage.target_path,
                k8s_pvc_name=pvc_name,
                created_by_id=old_storage.created_by_id,
                creation_date=old_storage.creation_date,
                updated_at=old_storage.updated_at,
            )
            .returning(project_storages_v2_table)
        )
        connection.execute(insert_storage_v2_stmt)


def downgrade() -> None:
    # NOTE: we cannot perform a "downgrade" operation for this migration.
    pass
