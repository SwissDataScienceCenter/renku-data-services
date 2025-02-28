from datetime import datetime

from ulid import ULID

from renku_data_services.authz.models import Visibility
from renku_data_services.base_models.core import Slug
from renku_data_services.solr.entity_documents import Group, Project, User

user_jan_ullrich = User(id="abc-def", firstName="Jan", lastName="Ullrich", namespace=Slug("janu"))
user_tadej_pogacar = User(id="hij-klm", firstName="Tadej", lastName="Pogačar", namespace=Slug("tadejp"))
group_team = Group(id=ULID(), name="The Team", namespace=Slug("the-team"), description="A group consisting of a team")
project_ai_stuff = Project(
    id=ULID(),
    name="AI stuff",
    slug=Slug("the-p1"),
    namespace=user_jan_ullrich.namespace,
    visibility=Visibility.PUBLIC,
    createdBy=user_jan_ullrich.id,
    creationDate=datetime(year=2025, month=1, day=31, hour=9, minute=47, second=44),
)


def test_user_dict():
    assert user_jan_ullrich.to_dict() == {
        "id": "abc-def",
        "namespace": "janu",
        "firstName": "Jan",
        "lastName": "Ullrich",
        "_type": "User",
        "_kind": "fullentity",
    }
    assert user_tadej_pogacar.to_dict() == {
        "id": "hij-klm",
        "namespace": "tadejp",
        "firstName": "Tadej",
        "lastName": "Pogačar",
        "_type": "User",
        "_kind": "fullentity",
    }


def test_read_user_dict():
    u1 = {
        "id": "abc-def",
        "namespace": "janu",
        "firstName": "Jan",
        "lastName": "Ullrich",
        "_type": "User",
        "_kind": "fullentity",
    }
    u = User.model_validate(u1)
    assert u == user_jan_ullrich


def test_group_dict():
    assert group_team.to_dict() == {
        "id": str(group_team.id),
        "name": "The Team",
        "namespace": "the-team",
        "description": "A group consisting of a team",
        "_type": "Group",
        "_kind": "fullentity",
    }


def test_read_group_dict():
    g = Group.model_validate(
        {
            "id": str(group_team.id),
            "name": "The Team",
            "namespace": "the-team",
            "description": "A group consisting of a team",
            "_type": "Group",
            "_kind": "fullentity",
        }
    )
    assert g == group_team


def test_project_dict():
    assert project_ai_stuff.to_dict() == {
        "id": str(project_ai_stuff.id),
        "name": "AI stuff",
        "slug": "the-p1",
        "namespace": "janu",
        "visibility": "public",
        "createdBy": "abc-def",
        "creationDate": "2025-01-31T09:47:44Z",
        "_type": "Project",
        "_kind": "fullentity",
    }


def test_read_project_dict():
    p = Project.model_validate(
        {
            "id": str(project_ai_stuff.id),
            "name": "AI stuff",
            "slug": "the-p1",
            "namespace": "janu",
            "visibility": "public",
            "createdBy": "abc-def",
            "creationDate": "2025-01-31T09:47:44Z",
            "_type": "Project",
            "_kind": "fullentity",
        }
    )
    assert p == project_ai_stuff
