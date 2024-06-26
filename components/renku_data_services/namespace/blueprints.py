"""Group blueprint."""

from dataclasses import dataclass

from sanic import HTTPResponse, Request, json
from sanic.response import JSONResponse
from sanic_ext import validate

import renku_data_services.base_models as base_models
from renku_data_services.base_api.auth import authenticate, only_authenticated
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.pagination import PaginationRequest, paginate
from renku_data_services.errors import errors
from renku_data_services.namespace import apispec
from renku_data_services.namespace.db import GroupRepository


@dataclass(kw_only=True)
class GroupsBP(CustomBlueprint):
    """Handlers for manipulating groups."""

    group_repo: GroupRepository
    authenticator: base_models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """List all groups."""

        @authenticate(self.authenticator)
        @paginate
        async def _get_all(
            _: Request, user: base_models.APIUser, pagination: PaginationRequest
        ) -> tuple[list[dict], int]:
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
        async def _post(_: Request, user: base_models.APIUser, body: apispec.GroupPostRequest) -> JSONResponse:
            result = await self.group_repo.insert_group(user=user, payload=body)
            return json(apispec.GroupResponse.model_validate(result).model_dump(exclude_none=True, mode="json"), 201)

        return "/groups", ["POST"], _post

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific group."""

        @authenticate(self.authenticator)
        async def _get_one(_: Request, user: base_models.APIUser, slug: str) -> JSONResponse:
            result = await self.group_repo.get_group(user=user, slug=slug)
            return json(apispec.GroupResponse.model_validate(result).model_dump(exclude_none=True, mode="json"))

        return "/groups/<slug>", ["GET"], _get_one

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific group."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete(_: Request, user: base_models.APIUser, slug: str) -> HTTPResponse:
            await self.group_repo.delete_group(user=user, slug=slug)
            return HTTPResponse(status=204)

        return "/groups/<slug>", ["DELETE"], _delete

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update a specific group."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.GroupPatchRequest)
        async def _patch(
            _: Request, user: base_models.APIUser, slug: str, body: apispec.GroupPatchRequest
        ) -> JSONResponse:
            body_dict = body.model_dump(exclude_none=True)
            res = await self.group_repo.update_group(user=user, slug=slug, payload=body_dict)
            return json(apispec.GroupResponse.model_validate(res).model_dump(exclude_none=True, mode="json"))

        return "/groups/<slug>", ["PATCH"], _patch

    def get_all_members(self) -> BlueprintFactoryResponse:
        """List all group members."""

        @authenticate(self.authenticator)
        async def _get_all_members(_: Request, user: base_models.APIUser, slug: str) -> JSONResponse:
            members = await self.group_repo.get_group_members(user, slug)
            return json(
                [
                    apispec.GroupMemberResponse(
                        id=m.id,
                        email=m.email,
                        first_name=m.first_name,
                        last_name=m.last_name,
                        role=apispec.GroupRole(m.role.value),
                    ).model_dump(exclude_none=True, mode="json")
                    for m in members
                ]
            )

        return "/groups/<slug>/members", ["GET"], _get_all_members

    def update_members(self) -> BlueprintFactoryResponse:
        """Update or add group members."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _update_members(
            request: Request,
            user: base_models.APIUser,
            slug: str,
        ) -> JSONResponse:
            body_validated = apispec.GroupMemberPatchRequestList.model_validate(request.json)
            res = await self.group_repo.update_group_members(
                user=user,
                slug=slug,
                payload=body_validated,
            )
            return json(
                [
                    apispec.GroupMemberPatchRequest(
                        id=m.member.user_id,
                        role=apispec.GroupRole(m.member.role.value),
                    ).model_dump(exclude_none=True, mode="json")
                    for m in res
                ]
            )

        return "/groups/<slug>/members", ["PATCH"], _update_members

    def delete_member(self) -> BlueprintFactoryResponse:
        """Remove a specific user from the list of members of a group."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete_member(_: Request, user: base_models.APIUser, slug: str, user_id: str) -> HTTPResponse:
            await self.group_repo.delete_group_member(user=user, slug=slug, user_id_to_delete=user_id)
            return HTTPResponse(status=204)

        return "/groups/<slug>/members/<user_id>", ["DELETE"], _delete_member

    def get_namespaces(self) -> BlueprintFactoryResponse:
        """Get all namespaces."""

        @authenticate(self.authenticator)
        @only_authenticated
        @paginate
        async def _get_namespaces(
            _: Request, user: base_models.APIUser, pagination: PaginationRequest
        ) -> tuple[list[dict], int]:
            nss, total_count = await self.group_repo.get_namespaces(user=user, pagination=pagination)
            return [
                apispec.NamespaceResponse(
                    id=ns.id,
                    name=ns.name,
                    slug=ns.latest_slug if ns.latest_slug else ns.slug,
                    created_by=ns.created_by,
                    creation_date=None,  # NOTE: we do not save creation date in the DB
                    namespace_kind=apispec.NamespaceKind(ns.kind.value),
                ).model_dump(exclude_none=True, mode="json")
                for ns in nss
            ], total_count

        return "/namespaces", ["GET"], _get_namespaces

    def get_namespace(self) -> BlueprintFactoryResponse:
        """Get namespace by slug."""

        @authenticate(self.authenticator)
        async def _get_namespace(_: Request, user: base_models.APIUser, slug: str) -> JSONResponse:
            ns = await self.group_repo.get_namespace_by_slug(user=user, slug=slug)
            if not ns:
                raise errors.MissingResourceError(message=f"The namespace with slug {slug} does not exist")
            return json(
                apispec.NamespaceResponse(
                    id=ns.id,
                    name=ns.name,
                    slug=ns.latest_slug if ns.latest_slug else ns.slug,
                    created_by=ns.created_by,
                    creation_date=None,  # NOTE: we do not save creation date in the DB
                    namespace_kind=apispec.NamespaceKind(ns.kind.value),
                ).model_dump(exclude_none=True, mode="json")
            )

        return "/namespaces/<slug>", ["GET"], _get_namespace
