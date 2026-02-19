"""Business logic for searching."""

import asyncio
from collections.abc import Iterable
from datetime import UTC, datetime

from authzed.api.v1 import (
    AsyncClient as AuthzClient,
)

import renku_data_services.search.apispec as apispec
import renku_data_services.search.solr_token as st
from renku_data_services.app_config import logging
from renku_data_services.authz.models import Role
from renku_data_services.base_models import APIUser
from renku_data_services.base_models.nel import Nel
from renku_data_services.search import authz, converters
from renku_data_services.search.db import SearchUpdatesRepo
from renku_data_services.search.models import DeleteDoc
from renku_data_services.search.solr_user_query import (
    AdminRole,
    AuthAccess,
    Context,
    QueryInterpreter,
    SolrUserQuery,
    UsernameResolve,
    UserRole,
)
from renku_data_services.search.user_query import UserQuery
from renku_data_services.solr.entity_documents import DataConnector, EntityDocReader, EntityType, Group, Project, User
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

logger = logging.getLogger(__name__)


async def update_solr(
    search_updates_repo: SearchUpdatesRepo, solr_client: SolrClient, batch_size: int
) -> list[Exception]:
    """Selects entries from the search staging table and updates SOLR."""
    counter = 0
    output: list[Exception] = []
    while True:
        entries = await search_updates_repo.select_next(batch_size)
        if entries == []:
            break

        ids = [e.id for e in entries]
        try:
            docs: list[SolrDocument] = [RawDocument(e.payload) for e in entries]
            result = await solr_client.upsert(docs)
            if result == "VersionConflict":
                logger.error(f"There was a version conflict updating search entities: {docs}")
                await search_updates_repo.mark_reset(ids)
                await asyncio.sleep(1)
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
                output.append(de)

        except Exception as e:
            output.append(e)
            logger.error(f"Error while updating solr with entities {ids}", exc_info=e)
            try:
                await search_updates_repo.mark_failed(ids)
            except Exception as e2:
                output.append(e2)
                logger.error("Error while setting search entities to failed", exc_info=e2)

    if counter > 0:
        logger.info(f"Updated {counter} entries in SOLR")

    return output


async def _renku_query(
    authz_client: AuthzClient, ctx: Context, uq: SolrUserQuery, limit: int, offset: int
) -> SolrQuery:
    """Create the final solr query embedding the given user query."""
    logger.debug(f"Searching as user: {ctx.role or "anonymous"}")
    role_constraint: list[str] = [st.public_only()]
    match ctx.role:
        case AdminRole():
            role_constraint = []
        case UserRole() as u:
            ids = await authz.get_non_public_read(authz_client, u.id, ctx.get_entity_types())
            role_constraint = [st.public_or_ids(ids)]

    return (
        SolrQuery.query_all_fields(uq.query_str(), limit, offset)
        .with_sort(uq.sort)
        .add_filter(
            st.created_by_exists(),
        )
        .add_filter(*role_constraint)
        .with_facet(FacetTerms(name=Fields.entity_type, field=Fields.entity_type))
        .with_facet(FacetTerms(name=Fields.keywords, field=Fields.keywords))
        .add_sub_query(
            Fields.creator_details,
            SubQuery(
                query="{!terms f=id v=$row.createdBy}", filter="{!terms f=_kind v=fullentity}", limit=1
            ).with_all_fields(),
        )
        .add_sub_query(
            Fields.namespace_details,
            SubQuery(
                query="{!terms f=path v=$row.namespacePath}",
                filter="(isNamespace:true AND _kind:fullentity)",
                limit=1,
            ).with_all_fields(),
        )
    )


async def _amend_counts_by_namespace(
    client: SolrClient,
    docs: list[apispec.SearchEntity],
    solr_docs: list[Group | Project | DataConnector | User],
    authz_client: AuthzClient,
    user: APIUser,
    ctx: Context,
) -> list[apispec.SearchEntity]:
    """Enrich user/group entities with project and data connector counts."""

    # Map id -> namespace path
    id_to_path: dict[str, str] = {str(doc.id): doc.path for doc in solr_docs if isinstance(doc, (Group, User))}

    if not id_to_path:
        return docs

    ns_paths = list(set(id_to_path.values()))

    project_counts, dc_counts = await asyncio.gather(
        _count_by_namespace(client, ns_paths, EntityType.project, authz_client, user, ctx),
        _count_by_namespace(client, ns_paths, EntityType.dataconnector, authz_client, user, ctx),
    )

    updated_docs: list[apispec.SearchEntity] = []

    for doc in docs:
        if isinstance(doc.root, (apispec.SearchGroup, apispec.SearchUser)):
            path = id_to_path.get(doc.root.id, "")
            updated_root = doc.root.model_copy(
                update={
                    "project_count": project_counts.get(path, 0),
                    "data_connector_count": dc_counts.get(path, 0),
                }
            )
            updated_docs.append(apispec.SearchEntity(root=updated_root))
        else:
            updated_docs.append(doc)

    return updated_docs


async def _count_by_namespace(
    solr_client: SolrClient,
    namespace_paths: list[str],
    entity_type: EntityType,
    authz_client: AuthzClient,
    user: APIUser,
    ctx: Context,
) -> dict[str, int]:
    """Count entities of a given type grouped by namespace path.

    Returns a dict mapping namespace_path -> count. Uses a single Solr
    query with a terms facet on namespacePath instead of one query per
    namespace.
    """
    if not namespace_paths:
        return {}

    role_constraint: list[str] = [st.public_only()]
    match ctx.role:
        case AdminRole():
            role_constraint = []
        case UserRole() as u:
            ids = await authz.get_non_public_read(authz_client, u.id, [entity_type])
            role_constraint = [st.public_or_ids(ids)]

    ns_tokens = Nel.unsafe_from_list([st.from_str(p) for p in namespace_paths])
    ns_filter = st.field_is_any(Fields.namespace_path, ns_tokens)
    count_query = (
        SolrQuery.query_all_fields("*:*", limit=0, offset=0)
        .add_filter(st.type_is(entity_type))
        .add_filter(ns_filter)
        .add_filter(st.created_by_exists())
        .add_filter(*role_constraint)
        .with_facet(FacetTerms(name=Fields.namespace_path, field=Fields.namespace_path, limit=len(namespace_paths)))
    )
    result = await solr_client.query(count_query)
    return result.facets.get_counts(Fields.namespace_path).to_simple_dict()


async def query(
    authz_client: AuthzClient,
    username_resolve: UsernameResolve,
    solr_config: SolrClientConfig,
    query: UserQuery,
    user: APIUser,
    limit: int,
    offset: int,
    include_counts: bool = False,
) -> apispec.SearchResult:
    """Run the given user query against solr and return the result."""

    logger.debug(f"User search query: {query.render()}")

    class RoleAuthAccess(AuthAccess):
        async def get_ids_for_role(
            self, user_id: str, roles: Nel[Role], ets: Iterable[EntityType], direct_membership: bool
        ) -> list[str]:
            return await authz.get_ids_for_roles(authz_client, user_id, roles, ets, direct_membership)

    ctx = (
        await Context.for_api_user(datetime.now(), UTC, user)
        .with_auth_access(RoleAuthAccess())
        .with_username_resolve(username_resolve)
        .with_requested_entity_types(query)
    )

    suq = await QueryInterpreter.default().run(ctx, query)
    solr_query = await _renku_query(authz_client, ctx, suq, limit, offset)
    logger.debug(f"Solr query: {solr_query.to_dict()}")

    async with DefaultSolrClient(solr_config) as client:
        results = await client.query(solr_query)
        total_pages = int(results.response.num_found / limit)
        if results.response.num_found % limit != 0:
            total_pages += 1

        solr_docs: list[Group | Project | DataConnector | User] = results.response.read_to(EntityDocReader.from_dict)

        docs = list(map(converters.from_entity, solr_docs))

        if include_counts:
            docs = await _amend_counts_by_namespace(client, docs, solr_docs, authz_client, user, ctx)

        return apispec.SearchResult(
            items=docs,
            facets=apispec.FacetData(
                entityType=apispec.MapEntityTypeInt(results.facets.get_counts(Fields.entity_type).to_simple_dict()),
                keywords=apispec.MapEntityTypeInt(results.facets.get_counts(Fields.keywords).to_simple_dict()),
            ),
            pagingInfo=apispec.PageWithTotals(
                page=apispec.PageDef(limit=limit, offset=offset),
                totalPages=int(total_pages),
                totalResult=results.response.num_found,
            ),
        )
