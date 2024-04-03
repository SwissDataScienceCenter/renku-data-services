"""cleanup project when slug is removed

Revision ID: 89aa4573cfa9
Revises: 87a439f35346
Create Date: 2024-04-02 13:01:02.124918

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '89aa4573cfa9'
down_revision = '87a439f35346'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Register a trigger and function to remove a project when its slug is removed.

    This is necessary because we only have a foreign key on the slugs table pointing to Projects, so
    we remove slugs when a project is removed. But we also want to remove projects when a slug is removed
    because this can occur when you delete a group and all projects within the group should also be deleted.
    """
    # NOTE: There may be projects left in DB whose slugs have been removed but the projects are present,
    # these should be cleaned up.
    op.execute("""DELETE FROM projects.projects
WHERE projects.id NOT IN (
SELECT project_slugs.project_id FROM projects.project_slugs
);""")
    # NOTE: OLD variable holds the name of the row that is being deleted (i.e. the trigger)
    op.execute("""CREATE OR REPLACE FUNCTION delete_project_after_slug_deletion()
RETURNS TRIGGER AS
$$
BEGIN
    DELETE FROM projects.projects WHERE projects.id = OLD.project_id;
    RETURN OLD;
END;
$$
LANGUAGE plpgsql;""")
    op.execute("""CREATE OR REPLACE TRIGGER delete_project_after_slug_deletion
AFTER DELETE ON projects.project_slugs
FOR EACH ROW
EXECUTE FUNCTION delete_project_after_slug_deletion();""")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS delete_project_after_slug_deletion on projects.project_slugs CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS delete_project_after_slug_deletion CASCADE;")
