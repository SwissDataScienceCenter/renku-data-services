from datetime import datetime

from ulid import ULID

from renku_data_services.authz.models import Visibility
from renku_data_services.base_models.core import Slug
from renku_data_services.solr.entity_documents import DataConnector, Group, Project, User

user_jan_ullrich = User.of(id="abc-def", firstName="Jan", lastName="Ullrich", slug=Slug("janu"))
user_tadej_pogacar = User.of(id="hij-klm", firstName="Tadej", lastName="Pogačar", slug=Slug("tadejp"))
group_team = Group.of(id=ULID(), name="The Team", slug=Slug("the-team"), description="A group consisting of a team")
project_ai_stuff = Project(
    id=ULID(),
    name="AI stuff",
    slug=Slug("the-p1"),
    path="the-p1",
    namespace_path=user_jan_ullrich.path,
    visibility=Visibility.PUBLIC,
    createdBy=user_jan_ullrich.id,
    creationDate=datetime(year=2025, month=1, day=31, hour=9, minute=47, second=44),
).in_namespace(user_jan_ullrich)

dc_one = DataConnector(
    id=ULID(),
    readonly=True,
    storageType="s3",
    name="qq dc one",
    slug=Slug("dc-xy1"),
    path="dc-xy1",
    visibility=Visibility.PUBLIC,
    createdBy=user_jan_ullrich.id,
    creationDate=datetime(year=2025, month=4, day=10, hour=16, minute=14, second=4),
    description="Bad data is filtered out.",
).in_namespace(user_jan_ullrich)

dc_global = DataConnector(
    id=ULID(),
    readonly=True,
    storageType="s3",
    name="qq dc global",
    slug=Slug("dc-global-1"),
    path="dc-global-1",
    visibility=Visibility.PUBLIC,
    createdBy=user_jan_ullrich.id,
    creationDate=datetime(year=2025, month=5, day=9, hour=11, minute=14, second=4),
    description="This is for all of us.",
).in_namespace(None)


def test_dc_project_keywords_sort() -> None:
    dc = DataConnector.from_dict(
        {
            "id": str(dc_one.id),
            "slug": "dc-xy1",
            "name": "qq dc one",
            "readonly": True,
            "storageType": "s3",
            "namespacePath": user_jan_ullrich.path,
            "path": f"{user_jan_ullrich.path}/dc-xy1",
            "createdBy": user_jan_ullrich.id,
            "creationDate": "2025-04-10T16:14:04Z",
            "description": "Bad data is filtered out.",
            "keywords": ["z", "a", "b"],
            "visibility": "public",
            "_kind": "fullentity",
            "_type": "DataConnector",
            "_version_": -1,
        }
    )
    assert dc.keywords == ["a", "b", "z"]

    p = Project.from_dict(
        {
            "id": str(project_ai_stuff.id),
            "name": "AI stuff",
            "slug": "the-p1",
            "namespacePath": user_jan_ullrich.path,
            "path": f"{user_jan_ullrich.path}/the-p1",
            "visibility": "public",
            "createdBy": "abc-def",
            "creationDate": "2025-01-31T09:47:44Z",
            "_type": "Project",
            "keywords": ["z", "b", "a"],
            "_kind": "fullentity",
            "_version_": -1,
        }
    )
    assert p.keywords == ["a", "b", "z"]


def test_dc_global_dict():
    assert dc_global.to_dict() == {
        "id": str(dc_global.id),
        "slug": "dc-global-1",
        "name": "qq dc global",
        "path": "dc-global-1",
        "isNamespace": False,
        "readonly": True,
        "storageType": "s3",
        "createdBy": user_jan_ullrich.id,
        "creationDate": "2025-05-09T11:14:04Z",
        "description": "This is for all of us.",
        "keywords": [],
        "visibility": "public",
        "_kind": "fullentity",
        "_type": "DataConnector",
        "_version_": -1,
    }


def test_read_dc_global_from_dict():
    dc = DataConnector.from_dict(
        {
            "id": str(dc_global.id),
            "slug": "dc-global-1",
            "name": "qq dc global",
            "path": "dc-global-1",
            "readonly": True,
            "storageType": "s3",
            "createdBy": user_jan_ullrich.id,
            "creationDate": "2025-05-09T11:14:04Z",
            "description": "This is for all of us.",
            "keywords": [],
            "visibility": "public",
            "_kind": "fullentity",
            "_type": "DataConnector",
            "_version_": -1,
        }
    )
    assert dc == dc_global


def test_dc_dict():
    assert dc_one.to_dict() == {
        "id": str(dc_one.id),
        "slug": "dc-xy1",
        "path": f"{user_jan_ullrich.path}/dc-xy1",
        "name": "qq dc one",
        "readonly": True,
        "storageType": "s3",
        "namespacePath": user_jan_ullrich.path,
        "createdBy": user_jan_ullrich.id,
        "creationDate": "2025-04-10T16:14:04Z",
        "description": "Bad data is filtered out.",
        "keywords": [],
        "visibility": "public",
        "isNamespace": False,
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
            "namespacePath": user_jan_ullrich.path,
            "path": f"{user_jan_ullrich.path}/dc-xy1",
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
        "slug": "janu",
        "path": "janu",
        "firstName": "Jan",
        "lastName": "Ullrich",
        "_type": "User",
        "_kind": "fullentity",
        "visibility": "public",
        "isNamespace": True,
        "_version_": -1,
    }
    assert user_tadej_pogacar.to_dict() == {
        "id": "hij-klm",
        "slug": "tadejp",
        "path": "tadejp",
        "firstName": "Tadej",
        "lastName": "Pogačar",
        "_type": "User",
        "_kind": "fullentity",
        "visibility": "public",
        "isNamespace": True,
        "_version_": -1,
    }


def test_read_user_dict():
    u1 = {
        "id": "abc-def",
        "path": "janu",
        "slug": "janu",
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
        "slug": "the-team",
        "path": "the-team",
        "description": "A group consisting of a team",
        "_type": "Group",
        "_kind": "fullentity",
        "visibility": "public",
        "isNamespace": True,
        "_version_": -1,
    }


def test_read_group_dict():
    g = Group.from_dict(
        {
            "id": str(group_team.id),
            "name": "The Team",
            "path": "the-team",
            "slug": "the-team",
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
        "path": f"{user_jan_ullrich.path}/the-p1",
        "namespacePath": user_jan_ullrich.path,
        "visibility": "public",
        "repositories": [],
        "keywords": [],
        "createdBy": "abc-def",
        "creationDate": "2025-01-31T09:47:44Z",
        "_type": "Project",
        "_kind": "fullentity",
        "isNamespace": True,
        "_version_": -1,
    }


def test_read_project_dict():
    p = Project.from_dict(
        {
            "id": str(project_ai_stuff.id),
            "name": "AI stuff",
            "slug": "the-p1",
            "namespacePath": user_jan_ullrich.path,
            "path": f"{user_jan_ullrich.path}/the-p1",
            "visibility": "public",
            "createdBy": "abc-def",
            "creationDate": "2025-01-31T09:47:44Z",
            "_type": "Project",
            "_kind": "fullentity",
            "_version_": -1,
        }
    )
    assert p == project_ai_stuff
