"""modify stored procedures

Revision ID: 8413f10ef77f
Revises: fe3b7470d226
Create Date: 2025-07-09 14:09:38.801974

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "8413f10ef77f"
down_revision = "fe3b7470d226"
branch_labels = None
depends_on = None

# NOTE: This combines the procedures introduced in migrations 89aa4573cfa9 and f4ad62b7b323.


def upgrade() -> None:
    op.execute("""CREATE OR REPLACE FUNCTION cleanup_after_slug_deletion()
RETURNS TRIGGER AS
$$
BEGIN
    IF OLD.project_id IS NOT NULL AND OLD.namespace_id IS NOT NULL AND OLD.data_connector_id IS NULL THEN
        DELETE FROM projects.projects WHERE projects.id = OLD.project_id;
    ELSIF old.project_id is NOT NULL AND old.namespace_id IS NOT NULL AND old.data_connector_id IS NOT NULL THEN
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
    op.execute("DROP TRIGGER IF EXISTS delete_project_after_slug_deletion ON common.entity_slugs;")
    # NOTE: The original slug table was in projects and then was renamed to common.entity_slugs, when
    # the table was renamed/moved to common the trigger was not updated but it still worked.
    op.execute("DROP TRIGGER IF EXISTS delete_project_after_slug_deletion ON projects.project_slugs;")
    op.execute("DROP FUNCTION IF EXISTS delete_project_after_slug_deletion;")
    op.execute("DROP TRIGGER IF EXISTS delete_data_connector_after_slug_deletion ON common.entity_slugs;")
    op.execute("DROP FUNCTION IF EXISTS delete_data_connector_after_slug_deletion;")


def downgrade() -> None:
    op.execute("""CREATE OR REPLACE FUNCTION delete_project_after_slug_deletion()
RETURNS TRIGGER AS
$$
BEGIN
    IF OLD.project_id IS NOT NULL AND OLD.namespace_id IS NOT NULL AND OLD.data_connector_id IS NULL THEN
        DELETE FROM projects.projects WHERE projects.id = OLD.project_id;
    END IF;
    RETURN OLD;
END;
$$
LANGUAGE plpgsql;""")
    op.execute("""CREATE OR REPLACE TRIGGER delete_project_after_slug_deletion
AFTER DELETE ON common.entity_slugs
FOR EACH ROW
EXECUTE FUNCTION delete_project_after_slug_deletion();""")
    op.execute("""CREATE OR REPLACE FUNCTION delete_data_connector_after_slug_deletion()
RETURNS TRIGGER AS
$$
BEGIN
    IF old.project_id is NOT NULL And old.namespace_id IS NOT NULL and old.data_connector_id IS NOT NULL THEN
        DELETE FROM storage.data_connectors WHERE data_connectors.id = OLD.data_connector_id;
    END IF;
    RETURN OLD;
END;
$$
LANGUAGE plpgsql;""")
    op.execute("""CREATE OR REPLACE TRIGGER delete_data_connector_after_slug_deletion
AFTER DELETE ON common.entity_slugs
FOR EACH ROW
EXECUTE FUNCTION delete_data_connector_after_slug_deletion();""")
    op.execute("DROP TRIGGER IF EXISTS cleanup_after_slug_deletion ON common.entity_slugs ;")
    op.execute("DROP FUNCTION IF EXISTS cleanup_after_slug_deletion;")
