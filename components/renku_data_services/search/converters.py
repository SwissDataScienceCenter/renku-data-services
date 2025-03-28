"""Conversion functions."""

from typing import cast

from renku_data_services.authz.models import Visibility
from renku_data_services.search.apispec import (
    Group as GroupApi,
)
from renku_data_services.search.apispec import (
    SearchProject as ProjectApi,
)
from renku_data_services.search.apispec import (
    User as UserApi,
)
from renku_data_services.search.apispec import (
    Visibility as VisibilityApi,
)
from renku_data_services.solr.entity_documents import (
    EntityDocReader,
)
from renku_data_services.solr.entity_documents import (
    Group as GroupDocument,
)
from renku_data_services.solr.entity_documents import (
    Project as ProjectDocument,
)
from renku_data_services.solr.entity_documents import (
    User as UserDocument,
)


def from_visibility(v: Visibility) -> VisibilityApi:
    """Creates a apispec visibility."""
    match v:
        case Visibility.PUBLIC:
            return VisibilityApi.public
        case Visibility.PRIVATE:
            return VisibilityApi.private


def from_user(user: UserDocument) -> UserApi:
    """Creates an apispec user from a solr user document."""
    return UserApi(
        id=user.id, namespace=user.namespace.value, firstName=user.firstName, lastName=user.lastName, score=user.score
    )


def from_group(group: GroupDocument) -> GroupApi:
    """Creates a apispec group from a solr group document."""
    return GroupApi(
        id=str(group.id),
        name=group.name,
        namespace=group.namespace.value,
        description=group.description,
        score=group.score,
    )


def from_project(project: ProjectDocument) -> ProjectApi:
    """Creates a apispec project from a solr project document."""
    cb: UserApi | None = None
    if project.creatorDetails is not None and project.creatorDetails.docs != []:
        cb = from_user(UserDocument.from_dict(project.creatorDetails.docs[0]))

    ns: UserApi | GroupApi | None = None
    if project.namespaceDetails is not None and project.namespaceDetails.docs != []:
        e = EntityDocReader.from_dict(project.namespaceDetails.docs[0])
        if e is not None:
            ns = cast(UserApi | GroupApi, from_entity(e))

    return ProjectApi(
        id=str(project.id),
        name=project.name,
        slug=project.slug.value,
        namespace=ns,
        repositories=project.repositories,
        visibility=from_visibility(project.visibility),
        description=project.description,
        createdBy=cb,
        creationDate=project.creationDate,
        keywords=project.keywords,
        score=project.score,
    )


def from_entity(entity: GroupDocument | ProjectDocument | UserDocument) -> UserApi | GroupApi | ProjectApi:
    """Creates an apispec entity from a solr entity document."""
    match entity:
        case UserDocument() as d:
            return from_user(d)
        case GroupDocument() as d:
            return from_group(d)
        case ProjectDocument() as d:
            return from_project(d)
