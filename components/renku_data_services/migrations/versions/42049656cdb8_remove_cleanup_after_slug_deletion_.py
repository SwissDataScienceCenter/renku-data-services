"""remove cleanup_after_slug_deletion trigger

Removes the cleanup trigger added in revision 8413f10ef77f

Revision ID: 42049656cdb8
Revises: d437be68a4fb
Create Date: 2025-10-23 09:55:19.905709

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "42049656cdb8"
down_revision = "d437be68a4fb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS cleanup_after_slug_deletion ON common.entity_slugs")
    op.execute("DROP FUNCTION cleanup_after_slug_deletion")


def downgrade() -> None:
    op.execute("""CREATE OR REPLACE FUNCTION cleanup_after_slug_deletion()
RETURNS TRIGGER AS
$$
BEGIN
    IF OLD.project_id IS NOT NULL AND OLD.data_connector_id IS NULL THEN
        DELETE FROM projects.projects WHERE projects.id = OLD.project_id;
    ELSIF old.data_connector_id IS NOT NULL THEN
        DELETE FROM storage.data_connectors WHERE data_connectors.id = OLD.data_connector_id;
    END IF;
    RETURN OLD;
END;
$$
LANGUAGE plpgsql;""")
    op.execute("""CREATE OR REPLACE TRIGGER cleanup_after_slug_deletion
AFTER DELETE ON common.entity_slugs
FOR EACH ROW
EXECUTE FUNCTION cleanup_after_slug_deletion();""")
