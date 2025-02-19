"""Search/reprovisioning blueprint."""

from dataclasses import dataclass

from sanic import HTTPResponse, Request, json
from sanic.response import JSONResponse

import renku_data_services.base_models as base_models
from renku_data_services.authz.authz import Authz
from renku_data_services.base_api.auth import authenticate, only_admins
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.message_queue.db import ReprovisioningRepository
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.project.db import ProjectRepository
from renku_data_services.search.core import reprovision
from renku_data_services.search.db import SearchUpdatesRepo
from renku_data_services.solr.solr_client import SolrClientConfig
from renku_data_services.users.db import UserRepo


@dataclass(kw_only=True)
class SearchBP(CustomBlueprint):
    """Handlers for search."""

    authenticator: base_models.Authenticator
    reprovisioning_repo: ReprovisioningRepository
    user_repo: UserRepo
    group_repo: GroupRepository
    project_repo: ProjectRepository
    search_updates_repo: SearchUpdatesRepo
    solr_config: SolrClientConfig
    authz: Authz

    def post(self) -> BlueprintFactoryResponse:
        """Start a new reprovisioning."""

        @authenticate(self.authenticator)
        @only_admins
        async def _post(request: Request, user: base_models.APIUser) -> HTTPResponse | JSONResponse:
            reprovisioning = await self.reprovisioning_repo.start()

            request.app.add_task(
                reprovision(
                    requested_by=user,
                    reprovisioning=reprovisioning,
                    search_updates_repo=self.search_updates_repo,
                    reprovisioning_repo=self.reprovisioning_repo,
                    solr_config=self.solr_config,
                    user_repo=self.user_repo,
                    group_repo=self.group_repo,
                    project_repo=self.project_repo,
                ),
                name=f"reprovisioning-{reprovisioning.id}",
            )

            return json({"id": str(reprovisioning.id), "start_date": reprovisioning.start_date.isoformat()}, 201)

        return "/search/reprovision", ["POST"], _post

    def get_status(self) -> BlueprintFactoryResponse:
        """Get reprovisioning status."""

        @authenticate(self.authenticator)
        async def _get_status(_: Request, __: base_models.APIUser) -> JSONResponse | HTTPResponse:
            reprovisioning = await self.reprovisioning_repo.get_active_reprovisioning()
            if not reprovisioning:
                return HTTPResponse(status=404)
            return json({"id": str(reprovisioning.id), "start_date": reprovisioning.start_date.isoformat()})

        return "/search/reprovision", ["GET"], _get_status

    def delete(self) -> BlueprintFactoryResponse:
        """Stop reprovisioning (if any)."""

        @authenticate(self.authenticator)
        @only_admins
        async def _delete(_: Request, __: base_models.APIUser) -> HTTPResponse:
            await self.reprovisioning_repo.stop()
            return HTTPResponse(status=204)

        return "/search/reprovision", ["DELETE"], _delete
