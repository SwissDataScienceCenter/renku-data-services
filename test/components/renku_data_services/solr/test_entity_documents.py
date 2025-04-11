from datetime import datetime

from ulid import ULID

from renku_data_services.authz.models import Visibility
from renku_data_services.base_models.core import Slug
from renku_data_services.solr.entity_documents import DataConnector, Group, Project, User

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
dc_one = DataConnector(
    id=ULID(),
    readonly=True,
    storageType="s3",
    projectId=project_ai_stuff.id,
    namespace=user_jan_ullrich.namespace,
    name="qq dc one",
    slug=Slug("dc-xy1"),
    visibility=Visibility.PUBLIC,
    createdBy=user_jan_ullrich.id,
    creationDate=datetime(year=2025, month=4, day=10, hour=16, minute=14, second=4),
    description="Bad data is filtered out.",
)


def test_dc_dict():
    assert dc_one.to_dict() == {
        "id": str(dc_one.id),
        "slug": "dc-xy1",
        "name": "qq dc one",
        "readonly": True,
        "storageType": "s3",
        "projectId": str(project_ai_stuff.id),
        "namespace": str(user_jan_ullrich.namespace),
        "createdBy": user_jan_ullrich.id,
        "creationDate": "2025-04-10T16:14:04Z",
        "description": "Bad data is filtered out.",
        "keywords": [],
        "visibility": "public",
        "_kind": "fullentity",
        "_type": "DataConnector",
        "_version_": -1,
    }


def test_read_dc_from_dict():
    dc = DataConnector.from_dict(
        {
            "id": str(dc_one.id),
            "slug": "dc-xy1",
            "name": "qq dc one",
            "readonly": True,
            "storageType": "s3",
            "projectId": str(project_ai_stuff.id),
            "namespace": str(user_jan_ullrich.namespace),
            "createdBy": user_jan_ullrich.id,
            "creationDate": "2025-04-10T16:14:04Z",
            "description": "Bad data is filtered out.",
            "keywords": [],
            "visibility": "public",
            "_kind": "fullentity",
            "_type": "DataConnector",
            "_version_": -1,
        }
    )
    assert dc == dc_one


def test_user_dict():
    assert user_jan_ullrich.to_dict() == {
        "id": "abc-def",
        "namespace": "janu",
        "firstName": "Jan",
        "lastName": "Ullrich",
        "_type": "User",
        "_kind": "fullentity",
        "visibility": "public",
        "_version_": -1,
    }
    assert user_tadej_pogacar.to_dict() == {
        "id": "hij-klm",
        "namespace": "tadejp",
        "firstName": "Tadej",
        "lastName": "Pogačar",
        "_type": "User",
        "_kind": "fullentity",
        "visibility": "public",
        "_version_": -1,
    }


def test_read_user_dict():
    u1 = {
        "id": "abc-def",
        "namespace": "janu",
        "firstName": "Jan",
        "lastName": "Ullrich",
        "_type": "User",
        "_kind": "fullentity",
        "visibility": "public",
        "_version_": -1,
    }
    u = User.from_dict(u1)
    assert u == user_jan_ullrich


def test_group_dict():
    assert group_team.to_dict() == {
        "id": str(group_team.id),
        "name": "The Team",
        "namespace": "the-team",
        "description": "A group consisting of a team",
        "_type": "Group",
        "_kind": "fullentity",
        "visibility": "public",
        "_version_": -1,
    }


def test_read_group_dict():
    g = Group.from_dict(
        {
            "id": str(group_team.id),
            "name": "The Team",
            "namespace": "the-team",
            "description": "A group consisting of a team",
            "_type": "Group",
            "_kind": "fullentity",
            "visibility": "public",
            "_version_": -1,
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
        "repositories": [],
        "keywords": [],
        "createdBy": "abc-def",
        "creationDate": "2025-01-31T09:47:44Z",
        "_type": "Project",
        "_kind": "fullentity",
        "_version_": -1,
    }


def test_read_project_dict():
    p = Project.from_dict(
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
            "_version_": -1,
        }
    )
    assert p == project_ai_stuff
