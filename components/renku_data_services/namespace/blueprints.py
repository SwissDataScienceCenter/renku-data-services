"""Group blueprint."""

from dataclasses import dataclass

from sanic import HTTPResponse, Request
from sanic.response import JSONResponse
from sanic_ext import validate

import renku_data_services.base_models as base_models
from renku_data_services.authz.models import Change, Role, UnsavedMember
from renku_data_services.base_api.auth import authenticate, only_authenticated, validate_path_user_id
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.misc import validate_query
from renku_data_services.base_api.pagination import PaginationRequest, paginate
from renku_data_services.base_models.core import NamespaceSlug, ProjectPath, Slug
from renku_data_services.base_models.metrics import MetricsService
from renku_data_services.base_models.validation import validate_and_dump, validated_json
from renku_data_services.errors import errors
from renku_data_services.namespace import apispec, apispec_enhanced, models
from renku_data_services.namespace.core import validate_group_patch
from renku_data_services.namespace.db import GroupRepository


@dataclass(kw_only=True)
class GroupsBP(CustomBlueprint):
    """Handlers for manipulating groups."""

    group_repo: GroupRepository
    authenticator: base_models.Authenticator
    metrics: MetricsService

    def get_all(self) -> BlueprintFactoryResponse:
        """List all groups."""

        @authenticate(self.authenticator)
        @validate_query(query=apispec_enhanced.GroupsGetParametersQuery)
        @paginate
        async def _get_all(
            _: Request,
            user: base_models.APIUser,
            pagination: PaginationRequest,
            query: apispec.GroupsGetParametersQuery,
        ) -> tuple[list[dict], int]:
            groups, rec_count = await self.group_repo.get_groups(
                user=user, pagination=pagination, direct_member=query.direct_member
            )
            return (
                validate_and_dump(apispec.GroupResponseList, groups),
                rec_count,
            )

        return "/groups", ["GET"], _get_all

    def post(self) -> BlueprintFactoryResponse:
        """Create a new group."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.GroupPostRequest)
        async def _post(_: Request, user: base_models.APIUser, body: apispec.GroupPostRequest) -> JSONResponse:
            new_group = models.UnsavedGroup(**body.model_dump())
            result = await self.group_repo.insert_group(user=user, payload=new_group)
            await self.metrics.group_created(user)
            return validated_json(apispec.GroupResponse, result, 201)

        return "/groups", ["POST"], _post

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific group."""

        @authenticate(self.authenticator)
        async def _get_one(_: Request, user: base_models.APIUser, slug: Slug) -> JSONResponse:
            result = await self.group_repo.get_group(user=user, slug=slug)
            return validated_json(apispec.GroupResponse, result)

        return "/groups/<slug:renku_slug>", ["GET"], _get_one

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific group."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete(_: Request, user: base_models.APIUser, slug: Slug) -> HTTPResponse:
            await self.group_repo.delete_group(user=user, slug=slug)
            return HTTPResponse(status=204)

        return "/groups/<slug:renku_slug>", ["DELETE"], _delete

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update a specific group."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.GroupPatchRequest)
        async def _patch(
            _: Request, user: base_models.APIUser, slug: Slug, body: apispec.GroupPatchRequest
        ) -> JSONResponse:
            group_patch = validate_group_patch(body)
            res = await self.group_repo.update_group(user=user, slug=slug, patch=group_patch)
            return validated_json(apispec.GroupResponse, data=res.new)

        return "/groups/<slug:renku_slug>", ["PATCH"], _patch

    def get_all_members(self) -> BlueprintFactoryResponse:
        """List all group members."""

        @authenticate(self.authenticator)
        async def _get_all_members(_: Request, user: base_models.APIUser, slug: Slug) -> JSONResponse:
            members = await self.group_repo.get_group_members(user, slug)
            return validated_json(
                apispec.GroupMemberResponseList,
                [
                    dict(
                        id=m.id,
                        first_name=m.first_name,
                        last_name=m.last_name,
                        role=apispec.GroupRole(m.role.value),
                        namespace=m.namespace,
                    )
                    for m in members
                ],
            )

        return "/groups/<slug:renku_slug>/members", ["GET"], _get_all_members

    def update_members(self) -> BlueprintFactoryResponse:
        """Update or add group members."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.GroupMemberPatchRequestList)
        async def _update_members(
            _: Request, user: base_models.APIUser, slug: Slug, body: apispec.GroupMemberPatchRequestList
        ) -> JSONResponse:
            members = [UnsavedMember(Role.from_group_role(member.role), member.id) for member in body.root]
            res = await self.group_repo.update_group_members(
                user=user,
                slug=slug,
                members=members,
            )

            if any(m.change == Change.ADD for m in res):
                await self.metrics.group_member_added(user)

            return validated_json(
                apispec.GroupMemberPatchRequestList,
                [
                    dict(
                        id=m.member.user_id,
                        role=apispec.GroupRole(m.member.role.value),
                    )
                    for m in res
                ],
            )

        return "/groups/<slug:renku_slug>/members", ["PATCH"], _update_members

    def delete_member(self) -> BlueprintFactoryResponse:
        """Remove a specific user from the list of members of a group."""

        @authenticate(self.authenticator)
        @validate_path_user_id
        @only_authenticated
        async def _delete_member(_: Request, user: base_models.APIUser, slug: Slug, user_id: str) -> HTTPResponse:
            await self.group_repo.delete_group_member(user=user, slug=slug, user_id_to_delete=user_id)
            return HTTPResponse(status=204)

        return "/groups/<slug:renku_slug>/members/<user_id>", ["DELETE"], _delete_member

    def get_permissions(self) -> BlueprintFactoryResponse:
        """Get the permissions of the current user on the group."""

        @authenticate(self.authenticator)
        async def _get_permissions(_: Request, user: base_models.APIUser, slug: Slug) -> JSONResponse:
            permissions = await self.group_repo.get_group_permissions(user=user, slug=slug)
            return validated_json(apispec.GroupPermissions, permissions)

        return "/groups/<slug:renku_slug>/permissions", ["GET"], _get_permissions

    def get_namespaces(self) -> BlueprintFactoryResponse:
        """Get all namespaces."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate_query(query=apispec_enhanced.NamespacesGetParametersQuery)
        @paginate
        async def _get_namespaces(
            request: Request,
            user: base_models.APIUser,
            pagination: PaginationRequest,
            query: apispec.NamespacesGetParametersQuery,
        ) -> tuple[list[dict], int]:
            minimum_role = Role.from_group_role(query.minimum_role) if query.minimum_role is not None else None
            if query.kinds:
                kinds = [models.NamespaceKind(kind.value) for kind in query.kinds]
            else:
                # NOTE: This is for API backwards compatibility reasons, removing or modifying
                # this default will result in a breaking API change.
                kinds = [models.NamespaceKind.group, models.NamespaceKind.user]

            nss, total_count = await self.group_repo.get_namespaces(
                user=user, pagination=pagination, minimum_role=minimum_role, kinds=kinds
            )
            return validate_and_dump(
                apispec.NamespaceResponseList,
                [
                    dict(
                        id=ns.id,
                        name=ns.name,
                        slug=ns.latest_slug
                        if ns.latest_slug
                        else (ns.path.second.value if isinstance(ns, models.ProjectNamespace) else ns.path.first.value),
                        created_by=ns.created_by,
                        creation_date=ns.creation_date,
                        namespace_kind=apispec.NamespaceKind(ns.kind.value),
                        path=ns.path.serialize(),
                    )
                    for ns in nss
                ],
            ), total_count

        return "/namespaces", ["GET"], _get_namespaces

    def get_namespace(self) -> BlueprintFactoryResponse:
        """Get user or group namespace by slug."""

        @authenticate(self.authenticator)
        async def _get_namespace(_: Request, user: base_models.APIUser, slug: Slug) -> JSONResponse:
            ns = await self.group_repo.get_namespace_by_slug(user=user, slug=NamespaceSlug(slug.value))
            if not ns:
                raise errors.MissingResourceError(message=f"The namespace with slug {slug} does not exist")
            return validated_json(
                apispec.NamespaceResponse,
                dict(
                    id=ns.id,
                    name=ns.name,
                    slug=ns.latest_slug or ns.path.last().value,
                    created_by=ns.created_by,
                    creation_date=None,  # NOTE: we do not save creation date in the DB
                    namespace_kind=apispec.NamespaceKind(ns.kind.value),
                    path=ns.path.serialize(),
                ),
            )

        return "/namespaces/<slug:renku_slug>", ["GET"], _get_namespace

    def get_namespace_second_level(self) -> BlueprintFactoryResponse:
        """Get project namespaces by slug (i.e. user1/projec2)."""

        @authenticate(self.authenticator)
        async def _get_namespace_second_level(
            _: Request, user: base_models.APIUser, first_slug: Slug, second_slug: Slug
        ) -> JSONResponse:
            path = ProjectPath.from_strings(first_slug.value, second_slug.value)
            ns = await self.group_repo.get_namespace_by_path(user=user, path=path)
            if not ns:
                raise errors.MissingResourceError(message=f"The namespace with slug {path} does not exist")
            return validated_json(
                apispec.NamespaceResponse,
                dict(
                    id=ns.id,
                    name=ns.name,
                    slug=ns.latest_slug or ns.path.last().value,
                    created_by=ns.created_by,
                    creation_date=None,  # NOTE: we do not save creation date in the DB
                    namespace_kind=apispec.NamespaceKind(ns.kind.value),
                    path=ns.path.serialize(),
                ),
            )

        return "/namespaces/<first_slug:renku_slug>/<second_slug:renku_slug>", ["GET"], _get_namespace_second_level
