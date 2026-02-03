"""Search/reprovisioning blueprint."""

from dataclasses import dataclass

from sanic import HTTPResponse, Request, json
from sanic.response import JSONResponse

import renku_data_services.base_models as base_models
import renku_data_services.search.core as core
from renku_data_services.app_config import logging
from renku_data_services.authz.authz import Authz
from renku_data_services.base_api.auth import authenticate, only_admins
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.misc import validate_query
from renku_data_services.base_models.metrics import MetricsService
from renku_data_services.search.apispec import SearchQuery
from renku_data_services.search.reprovision import SearchReprovision
from renku_data_services.search.solr_user_query import UsernameResolve
from renku_data_services.search.user_query_parser import QueryParser
from renku_data_services.solr.solr_client import SolrClientConfig

logger = logging.getLogger(__name__)


@dataclass(kw_only=True)
class SearchBP(CustomBlueprint):
    """Handlers for search."""

    authenticator: base_models.Authenticator
    solr_config: SolrClientConfig
    search_reprovision: SearchReprovision
    authz: Authz
    username_resolve: UsernameResolve
    metrics: MetricsService

    def post(self) -> BlueprintFactoryResponse:
        """Start a new reprovisioning."""

        @authenticate(self.authenticator)
        @only_admins
        async def _post(request: Request, user: base_models.APIUser) -> HTTPResponse | JSONResponse:
            reprovisioning = await self.search_reprovision.acquire_reprovision()

            request.app.add_task(
                self.search_reprovision.init_reprovision(user, reprovisioning=reprovisioning),
                name=f"reprovisioning-{reprovisioning.id}",
            )

            return json({"id": str(reprovisioning.id), "start_date": reprovisioning.start_date.isoformat()}, 201)

        return "/search/reprovision", ["POST"], _post

    def get_status(self) -> BlueprintFactoryResponse:
        """Get reprovisioning status."""

        @authenticate(self.authenticator)
        async def _get_status(_: Request, __: base_models.APIUser) -> JSONResponse | HTTPResponse:
            reprovisioning = await self.search_reprovision.get_current_reprovision()
            if not reprovisioning:
                return HTTPResponse(status=404)
            return json({"id": str(reprovisioning.id), "start_date": reprovisioning.start_date.isoformat()})

        return "/search/reprovision", ["GET"], _get_status

    def delete(self) -> BlueprintFactoryResponse:
        """Stop reprovisioning (if any)."""

        @authenticate(self.authenticator)
        @only_admins
        async def _delete(_: Request, __: base_models.APIUser) -> HTTPResponse:
            await self.search_reprovision.kill_reprovision_lock()
            return HTTPResponse(status=204)

        return "/search/reprovision", ["DELETE"], _delete

    def query(self) -> BlueprintFactoryResponse:
        """Run a query."""

        @authenticate(self.authenticator)
        @validate_query(query=SearchQuery)
        async def _query(_: Request, user: base_models.APIUser, query: SearchQuery) -> HTTPResponse | JSONResponse:
            per_page = query.per_page
            offset = (query.page - 1) * per_page
            uq = await QueryParser.parse(query.q)
            logger.debug(f"Running search query: {query}")

            result = await core.query(
                self.authz.client,
                self.username_resolve,
                self.solr_config,
                uq,
                user,
                per_page,
                offset,
                include_counts=query.include_counts,
            )
            await self.metrics.search_queried(user)
            return json(
                result.model_dump(by_alias=True, exclude_none=True, mode="json"),
                headers={
                    "x-page": f"{query.page}",
                    "x-per-page": f"{per_page}",
                    "x-total": f"{result.pagingInfo.totalPages}",
                    "x-total-pages": f"{result.pagingInfo.totalPages}",
                },
            )

        return "/search/query", ["GET"], _query
