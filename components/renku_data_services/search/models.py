"""Model classes for search."""

from pydantic import BaseModel
from ulid import ULID

from renku_data_services.namespace.models import Group
from renku_data_services.project.models import Project
from renku_data_services.users.models import UserInfo


class DeleteDoc(BaseModel):
    """A special payload for the staging table indicating to delete a document in solr."""

    doc_id: str
    entity_type: str

    @classmethod
    def group(cls, id: ULID) -> "DeleteDoc":
        """For deleting a group."""
        return DeleteDoc(doc_id=str(id), entity_type="Group")

    @classmethod
    def project(cls, id: ULID) -> "DeleteDoc":
        """For deleting a project."""
        return DeleteDoc(doc_id=str(id), entity_type="Project")

    @classmethod
    def user(cls, id: str) -> "DeleteDoc":
        """For deleting a user."""
        return DeleteDoc(doc_id=id, entity_type="User")


Entity = UserInfo | Group | Project | DeleteDoc
