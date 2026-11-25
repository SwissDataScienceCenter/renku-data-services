"""Add resource pool authorization schema

Revision ID: cd424c01676e
Revises: c6af6a1088f1
Create Date: 2026-03-26 15:30:31.073961

"""

import sqlalchemy as sa
from alembic import op
from authzed.api.v1 import (
    ObjectReference,
    Relationship,
    RelationshipUpdate,
    SubjectReference,
    WriteRelationshipsRequest,
)
from sqlalchemy.sql import text

from renku_data_services.app_config import logging
from renku_data_services.authz.authz import _AuthzConverter, _Relation
from renku_data_services.authz.config import AuthzConfig
from renku_data_services.authz.schemas import v9
from renku_data_services.base_models.core import ResourceType

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision = "cd424c01676e"
down_revision = "68d751fb3525"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    config = AuthzConfig.from_env()
    client = config.authz_client()

    # Schema must always come first
    client.WriteSchema(v9.up[0])
    logger.info("Upgraded Authzed schema to v9")

    inspector = sa.inspect(conn)

    if "resource_pools" not in inspector.get_schema_names():
        logger.info("resource_pools schema does not exist, skipping data migration")
        return

    if "resource_pools" not in inspector.get_table_names(schema="resource_pools"):
        logger.info("resource_pools.resource_pools table does not exist, skipping data migration")
        return

    platform_ref = _AuthzConverter.platform()
    user_wildcard = SubjectReference(object=ObjectReference(object_type=ResourceType.user, object_id="*"))
    anon_wildcard = SubjectReference(object=ObjectReference(object_type=ResourceType.anonymous_user, object_id="*"))

    pools = conn.execute(text('SELECT id, public, "default" FROM resource_pools.resource_pools')).fetchall()

    if not pools:
        logger.info("No resource pools found, skipping data migration")
        return

    updates: list[RelationshipUpdate] = []
    default_pool_id: int | None = None
    for row in pools:
        pool_id, is_public, is_default = int(row[0]), row[1], row[2]
        pool_ref = _AuthzConverter.resource_pool(pool_id)
        if is_default:
            default_pool_id = pool_id

        # Every pool needs to be linked to the platform
        updates.append(
            RelationshipUpdate(
                operation=RelationshipUpdate.OPERATION_TOUCH,
                relationship=Relationship(
                    resource=pool_ref,
                    relation="resource_pool_platform",
                    subject=SubjectReference(object=platform_ref),
                ),
            )
        )

        if is_public:
            updates.extend(
                [
                    RelationshipUpdate(
                        operation=RelationshipUpdate.OPERATION_TOUCH,
                        relationship=Relationship(resource=pool_ref, relation="public_viewer", subject=user_wildcard),
                    ),
                    RelationshipUpdate(
                        operation=RelationshipUpdate.OPERATION_TOUCH,
                        relationship=Relationship(resource=pool_ref, relation="public_viewer", subject=anon_wildcard),
                    ),
                ]
            )

    # Migrate existing pool viewers via the resource_pools_users join table
    # keycloak_id is the user identifier used in Authzed
    viewers = conn.execute(
        text("""
        SELECT rpu.resource_pool_id, u.keycloak_id
        FROM resource_pools.resource_pools_users rpu
        JOIN resource_pools.users u ON u.id = rpu.user_id
    """)
    ).fetchall()

    for row in viewers:
        pool_ref = _AuthzConverter.resource_pool(int(row[0]))
        user_ref = SubjectReference(object=ObjectReference(object_type=ResourceType.user, object_id=row[1]))
        updates.append(
            RelationshipUpdate(
                operation=RelationshipUpdate.OPERATION_TOUCH,
                relationship=Relationship(resource=pool_ref, relation=_Relation.viewer.value, subject=user_ref),
            )
        )

    # Users with no_default_access must be prohibited from the default pool.
    # The default pool is public, so without a "prohibited" relation these
    # users would still pass the public_viewer wildcard check.
    if default_pool_id is not None:
        no_access_users = conn.execute(
            text("SELECT keycloak_id FROM resource_pools.users WHERE no_default_access = true")
        ).fetchall()

        default_pool_ref = _AuthzConverter.resource_pool(default_pool_id)
        for user_row in no_access_users:
            user_ref = SubjectReference(object=ObjectReference(object_type=ResourceType.user, object_id=user_row[0]))
            updates.append(
                RelationshipUpdate(
                    operation=RelationshipUpdate.OPERATION_TOUCH,
                    relationship=Relationship(
                        resource=default_pool_ref,
                        relation=_Relation.prohibited.value,
                        subject=user_ref,
                    ),
                )
            )

        logger.info(f"Marked {len(no_access_users)} user(s) as prohibited on default pool {default_pool_id}")

    BATCH_SIZE = 500
    for i in range(0, len(updates), BATCH_SIZE):
        batch = updates[i : i + BATCH_SIZE]
        try:
            client.WriteRelationships(WriteRelationshipsRequest(updates=batch))
        except Exception as e:
            logger.error(
                f"Failed writing batch {i // BATCH_SIZE + 1}. "
                "This migration is idempotent. Re-run via `alembic upgrade`."
            )
            raise e

    logger.info(f"Migrated {len(pools)} resource pools and {len(viewers)} memberships to Authzed")


def downgrade() -> None:
    config = AuthzConfig.from_env()
    client = config.authz_client()
    responses = v9.downgrade(client)
    logger.info(f"Downgraded Authzed schema from v9: {responses}")
