"""Business logic for searching."""

from datetime import UTC, datetime

from authzed.api.v1 import AsyncClient as AuthzClient
from authzed.api.v1 import LookupResourcesRequest, ObjectReference, SubjectReference
from sanic.log import logger

import renku_data_services.search.apispec as apispec
import renku_data_services.search.solr_token as st
from renku_data_services.base_models import APIUser
from renku_data_services.message_queue.db import ReprovisioningRepository
from renku_data_services.message_queue.models import Reprovisioning
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.project.db import ProjectRepository
from renku_data_services.search import converters
from renku_data_services.search.db import SearchUpdatesRepo
from renku_data_services.search.models import DeleteDoc
from renku_data_services.search.solr_user_query import (
    AdminRole,
    Context,
    QueryInterpreter,
    SearchRole,
    SolrUserQuery,
    UserRole,
)
from renku_data_services.search.user_query import UserQuery
from renku_data_services.solr.entity_documents import EntityDocReader, EntityType, Group, Project, User
from renku_data_services.solr.entity_schema import Fields
from renku_data_services.solr.solr_client import (
    DefaultSolrClient,
    FacetTerms,
    RawDocument,
    SolrClient,
    SolrClientConfig,
    SolrDocument,
    SolrQuery,
    SubQuery,
)
from renku_data_services.users.db import UserRepo


async def reprovision(
    requested_by: APIUser,
    reprovisioning: Reprovisioning,
    search_updates_repo: SearchUpdatesRepo,
    reprovisioning_repo: ReprovisioningRepository,
    solr_config: SolrClientConfig,
    user_repo: UserRepo,
    group_repo: GroupRepository,
    project_repo: ProjectRepository,
) -> None:
    """Initiates reprovisioning by inserting documents into the staging table."""

    def log_counter(c: int) -> None:
        if c % 50 == 0:
            logger.info(f"Inserted {c}. entities into staging table...")

    try:
        logger.info(f"Starting reprovisioning with ID {reprovisioning.id}")
        started = datetime.now()
        await search_updates_repo.clear_all()
        async with DefaultSolrClient(solr_config) as client:
            await client.delete("_type:*")
        counter = 0
        all_users = user_repo.get_all_users(requested_by=requested_by)
        async for user_entity in all_users:
            await search_updates_repo.insert(user_entity, started)
            counter += 1
            log_counter(counter)

        all_groups = group_repo.get_all_groups(requested_by=requested_by)
        async for group_entity in all_groups:
            await search_updates_repo.insert(group_entity, started)
            counter += 1
            log_counter(counter)

        all_projects = project_repo.get_all_projects(requested_by=requested_by)
        async for project_entity in all_projects:
            await search_updates_repo.insert(project_entity, started)
            counter += 1
            log_counter(counter)

        logger.info(f"Inserted {counter} entities into the staging table.")

    except Exception as e:
        logger.error("Error while reprovisioning entities!", exc_info=e)
        ## TODO error handling. skip or fail?
    finally:
        await reprovisioning_repo.stop()


async def update_solr(search_updates_repo: SearchUpdatesRepo, solr_client: SolrClient, batch_size: int) -> None:
    """Selects entries from the search staging table and updates SOLR."""
    counter = 0
    while True:
        entries = await search_updates_repo.select_next(batch_size)
        if entries == []:
            break

        ids = [e.id for e in entries]
        try:
            docs: list[SolrDocument] = [RawDocument(e.payload) for e in entries]
            result = await solr_client.upsert(docs)
            if result == "VersionConflict":
                await search_updates_repo.mark_reset(ids)
            else:
                counter = counter + len(entries)
                await search_updates_repo.mark_processed(ids)

            try:
                # In the above upsert, documents could get
                # "soft-deleted". This would finally remove them. As
                # the success of this is not production critical,
                # errors are only logged
                await solr_client.delete(DeleteDoc.solr_query())
            except Exception as de:
                logger.error("Error when removing soft-deleted documents", exc_info=de)

        except Exception as e:
            logger.error(f"Error while updating solr with entities {ids}", exc_info=e)
            try:
                await search_updates_repo.mark_failed(ids)
            except Exception as e2:
                logger.error("Error while setting search entities to failed", exc_info=e2)

    if counter > 0:
        logger.info(f"Updated {counter} entries in SOLR")


async def _list_non_pubic_ids(authz_client: AuthzClient, user_id: str) -> list[str]:
    """Find all entity ids the user has read access to.

    For keeping the payload and the subsequent query small, it should
    return only private entities.
    """

    relation_name = "non_public_read"
    not_applicable_et: list[EntityType] = [EntityType.user]  # these types don't have the above relation
    user_ref = SubjectReference(object=ObjectReference(object_type="user", object_id=user_id))
    result: list[str] = []

    for et in EntityType:
        if et not in not_applicable_et:
            req = LookupResourcesRequest(
                resource_object_type=et.value.lower(), permission=relation_name, subject=user_ref
            )
            response = authz_client.LookupResources(req)
            async for o in response:
                result.append(o.resource_object_id)

    logger.debug(f"Found private ids for user '{user_id}': {result}")
    return result


async def _renku_query(
    authz_client: AuthzClient, ctx: Context, uq: SolrUserQuery, limit: int, offset: int
) -> SolrQuery:
    """Create the final solr query embedding the given user query."""
    role_constraint: list[str] = [st.public_only()]
    match ctx.role:
        case AdminRole():
            role_constraint = []
        case UserRole() as u:
            ids = await _list_non_pubic_ids(authz_client, u.id)
            role_constraint = [st.public_or_ids(ids)]

    return (
        SolrQuery.query_all_fields(uq.query_str(), limit, offset)
        .with_sort(uq.sort)
        .add_filter(
            st.namespace_exists(),
            st.created_by_exists(),
            "{!join from=namespace to=namespace}(_type:User OR _type:Group)",
        )
        .add_filter(*role_constraint)
        .with_facet(FacetTerms(name=Fields.entity_type, field=Fields.entity_type))
        .add_sub_query(
            Fields.creator_details,
            SubQuery(
                query="{!terms f=id v=$row.createdBy}", filter="{!terms f=_kind v=fullentity}", limit=1
            ).with_all_fields(),
        )
        .add_sub_query(
            Fields.namespace_details,
            SubQuery(
                query="{!terms f=namespace v=$row.namespace}",
                filter="((_type:User OR _type:Group) AND _kind:fullentity)",
                limit=1,
            ).with_all_fields(),
        )
    )


async def query(
    authz_client: AuthzClient, solr_config: SolrClientConfig, query: UserQuery, user: APIUser, limit: int, offset: int
) -> apispec.SearchResult:
    """Run the given user query against solr and return the result."""

    logger.info(f"User search query: {query.render()}")
    role: SearchRole | None = None
    if user.is_authenticated:
        role = UserRole(user.id or "")
    if user.is_admin:
        role = AdminRole(user.id or "")

    ctx = Context(datetime.now(), UTC, role)
    suq = QueryInterpreter.default().run(ctx, query)
    solr_query = await _renku_query(authz_client, ctx, suq, limit, offset)
    logger.info(f"Solr query: {solr_query.to_dict()}")

    async with DefaultSolrClient(solr_config) as client:
        results = await client.query(solr_query)
        total_pages = int(results.response.num_found / limit)
        if results.response.num_found % limit != 0:
            total_pages += 1

        solr_docs: list[Group | Project | User] = results.response.read_to(EntityDocReader.from_dict)

        docs = list(map(converters.from_entity, solr_docs))
        return apispec.SearchResult(
            items=docs,
            facets=apispec.FacetData(entityType=results.facets.get_counts(Fields.entity_type).to_simple_dict()),
            pagingInfo=apispec.PageWithTotals(
                page=apispec.PageDef(limit=limit, offset=offset),
                totalPages=int(total_pages),
                totalResult=results.response.num_found,
            ),
        )
