"""Model classes for search."""

from typing import Any

from pydantic import BaseModel
from ulid import ULID

from renku_data_services.namespace.models import Group
from renku_data_services.project.models import Project
from renku_data_services.users.models import UserInfo


class DeleteDoc(BaseModel):
    """A special payload for the staging table indicating to delete a document in solr."""

    id: str
    entity_type: str

    def to_dict(self) -> dict[str, Any]:
        """Return the dict representation."""
        return {"id": self.id, "deleted": True}

    @classmethod
    def solr_query(cls) -> str:
        """Returns the solr query that would select all documents of this type."""
        return "deleted:true"

    @classmethod
    def group(cls, id: ULID) -> "DeleteDoc":
        """For deleting a group."""
        return DeleteDoc(id=str(id), entity_type="Group")

    @classmethod
    def project(cls, id: ULID) -> "DeleteDoc":
        """For deleting a project."""
        return DeleteDoc(id=str(id), entity_type="Project")

    @classmethod
    def user(cls, id: str) -> "DeleteDoc":
        """For deleting a user."""
        return DeleteDoc(id=id, entity_type="User")


Entity = UserInfo | Group | Project | DeleteDoc
