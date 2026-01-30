"""Conversion functions."""

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
    UserOrGroupOrProject,
)
from renku_data_services.search.apispec import (
    SearchGroup as SearchGroupApi,
)
from renku_data_services.search.apispec import (
    SearchProject as ProjectApi,
)
from renku_data_services.search.apispec import (
    SearchUser as SearchUserApi,
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


def from_user(user: UserDocument) -> SearchUserApi:
    """Creates an apispec user from a solr user document."""
    return SearchUserApi(
        id=user.id,
        slug=user.slug.value,
        path=user.path,
        firstName=user.firstName,
        lastName=user.lastName,
        score=user.score,
        project_count=None,
        data_connector_count=None,
    )


def from_group(group: GroupDocument) -> SearchGroupApi:
    """Creates a apispec group from a solr group document."""
    return SearchGroupApi(
        id=str(group.id),
        name=group.name,
        slug=group.slug.value,
        path=group.path,
        description=group.description,
        score=group.score,
        project_count=None,
        data_connector_count=None,
        members_count=None,
    )


def __creator_details(e: ProjectDocument | DataConnectorDocument) -> UserApi | None:
    if e.creatorDetails is not None and e.creatorDetails.docs != []:
        return __user_to_base(UserDocument.from_dict(e.creatorDetails.docs[0]))
    else:
        return None


def __user_to_base(user: UserDocument) -> UserApi:
    """Creates a base User (not SearchUser) from a solr user document."""
    return UserApi(
        id=user.id,
        slug=user.slug.value,
        path=user.path,
        firstName=user.firstName,
        lastName=user.lastName,
        score=user.score,
    )


def __group_to_base(group: GroupDocument) -> GroupApi:
    """Creates a base Group (not SearchGroup) from a solr group document."""
    return GroupApi(
        id=str(group.id),
        name=group.name,
        slug=group.slug.value,
        path=group.path,
        description=group.description,
        score=group.score,
    )


def __namespace_details(d: ProjectDocument) -> UserOrGroup | None:
    if d.namespaceDetails is not None and d.namespaceDetails.docs != []:
        e = EntityDocReader.from_dict(d.namespaceDetails.docs[0])
        if e is not None:
            match e:
                case UserDocument() as user_doc:
                    return UserOrGroup(__user_to_base(user_doc))
                case GroupDocument() as group_doc:
                    return UserOrGroup(__group_to_base(group_doc))
    return None


def __namespace_details_dc(d: DataConnectorDocument) -> UserOrGroupOrProject | None:
    if d.namespaceDetails is not None and d.namespaceDetails.docs != []:
        e = EntityDocReader.from_dict(d.namespaceDetails.docs[0])
        if e is not None:
            match e:
                case UserDocument() as user_doc:
                    return UserOrGroupOrProject(__user_to_base(user_doc))
                case GroupDocument() as group_doc:
                    return UserOrGroupOrProject(__group_to_base(group_doc))
                case ProjectDocument() as project_doc:
                    return UserOrGroupOrProject(from_project(project_doc))
    return None


def from_project(project: ProjectDocument) -> ProjectApi:
    """Creates a apispec project from a solr project document."""
    return ProjectApi(
        id=str(project.id),
        name=project.name,
        slug=project.slug.value,
        path=project.path,
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
        path=dc.path,
        namespace=__namespace_details_dc(dc),
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
