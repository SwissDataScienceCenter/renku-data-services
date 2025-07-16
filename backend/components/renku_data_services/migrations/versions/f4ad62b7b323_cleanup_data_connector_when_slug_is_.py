"""Cleanup data connector when slug is removed

Revision ID: f4ad62b7b323
Revises: dcb9648c3c15
Create Date: 2025-05-19 07:15:11.989650

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f4ad62b7b323"
down_revision = "dcb9648c3c15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Register a trigger and function to remove a data connector when its slug is removed.

    This is necessary because we only have a foreign key on the slugs table pointing to Data Connectors, so
    we remove slugs when a data connector is removed. But we also want to remove projects when a slug is removed
    because this can occur when you delete a group and all data connectors within the group should also be deleted."""
    op.execute(sa.text("LOCK TABLE common.entity_slugs IN EXCLUSIVE MODE"))
    op.execute(sa.text("LOCK TABLE storage.data_connectors IN EXCLUSIVE MODE"))
    # NOTE: OLD variable holds the name of the row that is being deleted (i.e. the trigger)
    op.execute("""CREATE OR REPLACE FUNCTION delete_data_connector_after_slug_deletion()
RETURNS TRIGGER AS
$$
BEGIN
    DELETE FROM storage.data_connectors WHERE data_connectors.id = OLD.data_connector_id;
    RETURN OLD;
END;
$$
LANGUAGE plpgsql;""")
    op.execute("""CREATE OR REPLACE TRIGGER delete_data_connector_after_slug_deletion
AFTER DELETE ON common.entity_slugs
FOR EACH ROW
EXECUTE FUNCTION delete_data_connector_after_slug_deletion();""")
    # NOTE: Here we cleanup the data connectors which have neither a namespaced slug nor a global slug.
    op.execute("""DELETE FROM storage.data_connectors
WHERE data_connectors.id NOT IN (
    SELECT entity_slugs.data_connector_id FROM common.entity_slugs WHERE entity_slugs.data_connector_id IS NOT NULL
) AND data_connectors.global_slug IS NULL""")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS delete_data_connector_after_slug_deletion ON storage.data_connectors CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS delete_data_connector_after_slug_deletion CASCADE;")
