"""Conversion functions."""

from typing import cast

from renku_data_services.authz.models import Visibility
from renku_data_services.search.apispec import (
    Group as GroupApi,
)
from renku_data_services.search.apispec import (
    SearchDataConnector as DataConnectorApi,
)
from renku_data_services.search.apispec import (
    SearchEntity,
    UserOrGroup,
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
    DataConnector as DataConnectorDocument,
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
    return UserApi(id=user.id, namespace=user.path, firstName=user.firstName, lastName=user.lastName, score=user.score)


def from_group(group: GroupDocument) -> GroupApi:
    """Creates a apispec group from a solr group document."""
    return GroupApi(
        id=str(group.id),
        name=group.name,
        namespace=group.path,
        description=group.description,
        score=group.score,
    )


def __creator_details(e: ProjectDocument | DataConnectorDocument) -> UserApi | None:
    if e.creatorDetails is not None and e.creatorDetails.docs != []:
        return from_user(UserDocument.from_dict(e.creatorDetails.docs[0]))
    else:
        return None


def __namespace_details(d: ProjectDocument | DataConnectorDocument) -> UserOrGroup | None:
    if d.namespaceDetails is not None and d.namespaceDetails.docs != []:
        e = EntityDocReader.from_dict(d.namespaceDetails.docs[0])
        if e is not None:
            return UserOrGroup(cast(UserApi | GroupApi, from_entity(e).root))
    return None


def from_project(project: ProjectDocument) -> ProjectApi:
    """Creates a apispec project from a solr project document."""
    return ProjectApi(
        id=str(project.id),
        name=project.name,
        slug=project.slug.value,
        namespace=__namespace_details(project),
        repositories=project.repositories,
        visibility=from_visibility(project.visibility),
        description=project.description,
        createdBy=__creator_details(project),
        creationDate=project.creationDate,
        keywords=project.keywords,
        score=project.score,
    )


def from_data_connector(dc: DataConnectorDocument) -> DataConnectorApi:
    """Creates an apispec data connector from a solr data connector document."""
    return DataConnectorApi(
        id=str(dc.id),
        name=dc.name,
        slug=dc.slug.value,
        namespace=__namespace_details(dc),
        visibility=from_visibility(dc.visibility),
        description=dc.description,
        createdBy=__creator_details(dc),
        creationDate=dc.creationDate,
        keywords=dc.keywords,
        storageType=dc.storageType,
        readonly=dc.readonly,
        score=dc.score,
    )


def from_entity(
    entity: GroupDocument | ProjectDocument | UserDocument | DataConnectorDocument,
) -> SearchEntity:
    """Creates an apispec entity from a solr entity document."""
    match entity:
        case UserDocument() as d:
            return SearchEntity(from_user(d))
        case GroupDocument() as d:
            return SearchEntity(from_group(d))
        case ProjectDocument() as d:
            return SearchEntity(from_project(d))
        case DataConnectorDocument() as d:
            return SearchEntity(from_data_connector(d))
