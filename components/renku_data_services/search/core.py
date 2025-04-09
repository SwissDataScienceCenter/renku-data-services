"""Business logic for searching."""

import asyncio
from datetime import UTC, datetime

from authzed.api.v1 import AsyncClient as AuthzClient
from sanic.log import logger

import renku_data_services.search.apispec as apispec
import renku_data_services.search.solr_token as st
from renku_data_services.authz.models import Role
from renku_data_services.base_models import APIUser
from renku_data_services.search import authz, converters
from renku_data_services.search.db import SearchUpdatesRepo
from renku_data_services.search.models import DeleteDoc
from renku_data_services.search.solr_user_query import (
    AdminRole,
    AuthAccess,
    Context,
    QueryInterpreter,
    SolrUserQuery,
    UserRole,
)
from renku_data_services.search.user_query import Nel, UserQuery
from renku_data_services.solr.entity_documents import EntityDocReader, Group, Project, User
from renku_data_services.solr.entity_schema import Fields
from renku_data_services.solr.solr_client import (
    DefaultSolrClient,
    DocVersions,
    FacetTerms,
    RawDocument,
    SolrClient,
    SolrClientConfig,
    SolrDocument,
    SolrQuery,
    SubQuery,
)


async def update_solr(search_updates_repo: SearchUpdatesRepo, solr_client: SolrClient, batch_size: int) -> None:
    """Selects entries from the search staging table and updates SOLR."""
    counter = 0
    while True:
        entries = await search_updates_repo.select_next(batch_size)
        if entries == []:
            break

        ids = [e.id for e in entries]
        try:
            docs: list[SolrDocument] = [RawDocument.create(e.payload, DocVersions.off()) for e in entries]
            result = await solr_client.upsert(docs)
            if result == "VersionConflict":
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

        except Exception as e:
            logger.error(f"Error while updating solr with entities {ids}", exc_info=e)
            try:
                await search_updates_repo.mark_failed(ids)
            except Exception as e2:
                logger.error("Error while setting search entities to failed", exc_info=e2)

    if counter > 0:
        logger.info(f"Updated {counter} entries in SOLR")


async def _renku_query(
    authz_client: AuthzClient, ctx: Context, uq: SolrUserQuery, limit: int, offset: int
) -> SolrQuery:
    """Create the final solr query embedding the given user query."""
    role_constraint: list[str] = [st.public_only()]
    match ctx.role:
        case AdminRole():
            role_constraint = []
        case UserRole() as u:
            ids = await authz.get_non_public_read(authz_client, u.id)
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

    class RoleAuthAccess(AuthAccess):
        async def get_role_ids(self, user_id: str, roles: Nel[Role]) -> list[str]:
            return await authz.get_role_ids(authz_client, user_id, roles)

    ctx = Context.for_api_user(datetime.now(), UTC, user).with_auth_access(RoleAuthAccess())
    suq = await QueryInterpreter.default().run(ctx, query)
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
