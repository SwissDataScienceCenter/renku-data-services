"""Group blueprint."""

from dataclasses import dataclass

from sanic import HTTPResponse, Request, json
from sanic_ext import validate

import renku_data_services.base_models as base_models
from renku_data_services.base_api.auth import authenticate, only_authenticated
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.pagination import PaginationRequest, paginate
from renku_data_services.group import apispec
from renku_data_services.group.db import GroupRepository


@dataclass(kw_only=True)
class ProjectsBP(CustomBlueprint):
    """Handlers for manipulating groups."""

    group_repo: GroupRepository
    authenticator: base_models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """List all groups."""

        @authenticate(self.authenticator)
        @paginate
        async def _get_all(_: Request, *, user: base_models.APIUser, pagination: PaginationRequest):
            groups, rec_count = await self.group_repo.get_groups(user=user, pagination=pagination)
            return (
                [apispec.GroupResponse.model_validate(g).model_dump(exclude_none=True, mode="json") for g in groups],
                rec_count,
            )

        return "/groups", ["GET"], _get_all

    def post(self) -> BlueprintFactoryResponse:
        """Create a new group."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.GroupPostRequest)
        async def _post(_: Request, *, user: base_models.APIUser, body: apispec.GroupPostRequest):
            result = await self.group_repo.insert_group(user=user, payload=body)
            return json(apispec.GroupResponse.model_validate(result).model_dump(exclude_none=True, mode="json"), 201)

        return "/groups", ["POST"], _post

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific group."""

        @authenticate(self.authenticator)
        async def _get_one(_: Request, *, user: base_models.APIUser, slug: str):
            result = await self.group_repo.get_group(slug=slug)
            return json(apispec.GroupResponse.model_validate(result).model_dump(exclude_none=True, mode="json"))

        return "/groups/<slug>", ["GET"], _get_one

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific group."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete(_: Request, *, user: base_models.APIUser, slug: str):
            await self.group_repo.delete_group(user=user, slug=slug)
            return HTTPResponse(status=204)

        return "/groups/<slug>", ["DELETE"], _delete

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update a specific group."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.GroupPatchRequest)
        async def _patch(_: Request, *, user: base_models.APIUser, slug: str, body: apispec.GroupPatchRequest):
            body_dict = body.model_dump(exclude_none=True)
            res = await self.group_repo.update_group(user=user, slug=slug, payload=body_dict)
            return json(apispec.GroupResponse.model_validate(res).model_dump(exclude_none=True, mode="json"))

        return "/groups/<slug>", ["PATCH"], _patch

    def get_all_members(self) -> BlueprintFactoryResponse:
        """List all group members."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _get_all_members(_: Request, *, user: base_models.APIUser, slug: str):
            members = await self.group_repo.get_group_members(user, slug)
            return json(
                [
                    apispec.GroupMemberResponse.model_validate(m).model_dump(exclude_none=True, mode="json")
                    for m in members
                ]
            )

        return "/groups/<slug>/members", ["GET"], _get_all_members

    def update_members(self) -> BlueprintFactoryResponse:
        """Update or add group members."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.GroupMemberPatchRequestList)
        async def _update_members(
            _: Request, *, user: base_models.APIUser, slug: str, body: apispec.GroupMemberPatchRequestList
        ):
            res = await self.group_repo.update_group_members(
                user=user,
                slug=slug,
                payload=body,
            )
            return json(
                [apispec.GroupMemberResponse.model_validate(i).model_dump(exclude_none=True, mode="json") for i in res]
            )

        return "/group/<slug>/members", ["PATCH"], _update_members

    def delete_member(self) -> BlueprintFactoryResponse:
        """Delete a specific project."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete_member(_: Request, *, user: base_models.APIUser, slug: str, user_id: str):
            await self.group_repo.delete_group_member(user=user, slug=slug, user_id_to_delete=user_id)
            return HTTPResponse(status=204)

        return "/group/<slug>/members/<user_id>", ["DELETE"], _delete_member
