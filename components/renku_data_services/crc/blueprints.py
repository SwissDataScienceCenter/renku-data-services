"""Compute resource control (CRC) app."""

import asyncio
from dataclasses import asdict, dataclass

from sanic import HTTPResponse, Request, empty, json
from sanic_ext import validate

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.base_api.auth import authenticate, only_admins
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.misc import validate_db_ids
from renku_data_services.crc import apispec, models
from renku_data_services.crc.apispec_base import ResourceClassesFilter
from renku_data_services.crc.db import ResourcePoolRepository, UserRepository
from renku_data_services.k8s.quota import QuotaRepository
from renku_data_services.users.db import UserRepo as KcUserRepo
from renku_data_services.users.models import UserInfo


@dataclass(kw_only=True)
class ResourcePoolsBP(CustomBlueprint):
    """Handlers for manipulating resource pools."""

    rp_repo: ResourcePoolRepository
    user_repo: UserRepository
    authenticator: base_models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """List all resource pools."""

        @authenticate(self.authenticator)
        async def _get_all(request: Request, user: base_models.APIUser) -> HTTPResponse:
            res_filter = ResourceClassesFilter.model_validate(dict(request.query_args))
            rps = await self.rp_repo.filter_resource_pools(api_user=user, **res_filter.dict())
            return json(
                [apispec.ResourcePoolWithIdFiltered.model_validate(r).model_dump(exclude_none=True) for r in rps]
            )

        return "/resource_pools", ["GET"], _get_all

    def post(self) -> BlueprintFactoryResponse:
        """Add a new resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.ResourcePool)
        async def _post(_: Request, user: base_models.APIUser, body: apispec.ResourcePool) -> HTTPResponse:
            rp = models.ResourcePool.from_dict(body.model_dump(exclude_none=True))
            res = await self.rp_repo.insert_resource_pool(api_user=user, resource_pool=rp)
            return json(apispec.ResourcePoolWithId.model_validate(res).model_dump(exclude_none=True), 201)

        return "/resource_pools", ["POST"], _post

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific resource pool."""

        @authenticate(self.authenticator)
        @validate_db_ids
        async def _get_one(request: Request, user: base_models.APIUser, resource_pool_id: int) -> HTTPResponse:
            rps: list[models.ResourcePool]
            rps = await self.rp_repo.get_resource_pools(
                api_user=user, id=resource_pool_id, name=request.args.get("name")
            )
            if len(rps) < 1:
                raise errors.MissingResourceError(
                    message=f"The resource pool with id {resource_pool_id} cannot be found."
                )
            rp = rps[0]
            return json(apispec.ResourcePoolWithId.model_validate(rp).model_dump(exclude_none=True))

        return "/resource_pools/<resource_pool_id>", ["GET"], _get_one

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        @validate_db_ids
        async def _delete(_: Request, user: base_models.APIUser, resource_pool_id: int) -> HTTPResponse:
            await self.rp_repo.delete_resource_pool(api_user=user, id=resource_pool_id)
            return HTTPResponse(status=204)

        return "/resource_pools/<resource_pool_id>", ["DELETE"], _delete

    def put(self) -> BlueprintFactoryResponse:
        """Update all fields of a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        @validate_db_ids
        @validate(json=apispec.ResourcePoolPut)
        async def _put(
            _: Request, user: base_models.APIUser, resource_pool_id: int, body: apispec.ResourcePoolPut
        ) -> HTTPResponse:
            res = await self.rp_repo.update_resource_pool(
                api_user=user,
                id=resource_pool_id,
                **body.model_dump(exclude_none=True),
            )
            if res is None:
                raise errors.MissingResourceError(
                    message=f"The resource pool with ID {resource_pool_id} cannot be found."
                )
            return json(apispec.ResourcePoolWithId.model_validate(res).model_dump(exclude_none=True))

        return "/resource_pools/<resource_pool_id>", ["PUT"], _put

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        @validate_db_ids
        @validate(json=apispec.ResourcePoolPatch)
        async def _patch(
            _: Request, user: base_models.APIUser, resource_pool_id: int, body: apispec.ResourcePoolPatch
        ) -> HTTPResponse:
            res = await self.rp_repo.update_resource_pool(
                api_user=user,
                id=resource_pool_id,
                **body.model_dump(exclude_none=True),
            )
            if res is None:
                raise errors.MissingResourceError(
                    message=f"The resource pool with ID {resource_pool_id} cannot be found."
                )
            return json(apispec.ResourcePoolWithId.model_validate(res).model_dump(exclude_none=True))

        return "/resource_pools/<resource_pool_id>", ["PATCH"], _patch


@dataclass(kw_only=True)
class ResourcePoolUsersBP(CustomBlueprint):
    """Handlers for dealing with the users of individual resource pools."""

    repo: UserRepository
    kc_user_repo: KcUserRepo
    authenticator: base_models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """Get all users of a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        @validate_db_ids
        async def _get_all(_: Request, user: base_models.APIUser, resource_pool_id: int) -> HTTPResponse:
            res = await self.repo.get_resource_pool_users(api_user=user, resource_pool_id=resource_pool_id)
            return json(
                [
                    apispec.PoolUserWithId(id=r.keycloak_id, no_default_access=r.no_default_access).model_dump(
                        exclude_none=True
                    )
                    for r in res.allowed
                ]
            )

        return "/resource_pools/<resource_pool_id>/users", ["GET"], _get_all

    def post(self) -> BlueprintFactoryResponse:
        """Add users to a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        @validate_db_ids
        async def _post(request: Request, user: base_models.APIUser, resource_pool_id: int) -> HTTPResponse:
            users = apispec.PoolUsersWithId.model_validate(request.json)  # validation
            return await self._put_post(api_user=user, resource_pool_id=resource_pool_id, body=users, post=True)

        return "/resource_pools/<resource_pool_id>/users", ["POST"], _post

    def put(self) -> BlueprintFactoryResponse:
        """Set the users for a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        @validate_db_ids
        async def _put(request: Request, user: base_models.APIUser, resource_pool_id: int) -> HTTPResponse:
            users = apispec.PoolUsersWithId.model_validate(request.json)  # validation
            return await self._put_post(api_user=user, resource_pool_id=resource_pool_id, body=users, post=False)

        return "/resource_pools/<resource_pool_id>/users", ["PUT"], _put

    async def _put_post(
        self, api_user: base_models.APIUser, resource_pool_id: int, body: apispec.PoolUsersWithId, post: bool = True
    ) -> HTTPResponse:
        user_ids_to_add = set([user.id for user in body.root])
        users_checks: list[UserInfo | None] = await asyncio.gather(
            *[self.kc_user_repo.get_user(requested_by=api_user, id=id) for id in user_ids_to_add]
        )
        existing_user_ids = set([user.id for user in users_checks if user is not None])
        if existing_user_ids != user_ids_to_add:
            missing_ids = user_ids_to_add.difference(existing_user_ids)
            raise errors.MissingResourceError(message=f"The users with IDs {missing_ids} cannot be found")
        updated_users = await self.repo.update_resource_pool_users(
            api_user=api_user,
            resource_pool_id=resource_pool_id,
            user_ids=user_ids_to_add,
            append=post,
        )
        return json(
            [
                apispec.PoolUserWithId(id=r.keycloak_id, no_default_access=r.no_default_access).model_dump(
                    exclude_none=True
                )
                for r in updated_users
            ],
            status=201 if post else 200,
        )

    def get(self) -> BlueprintFactoryResponse:
        """Check if a specific user has access to a resource pool."""

        @authenticate(self.authenticator)
        @validate_db_ids
        async def _get(_: Request, user: base_models.APIUser, resource_pool_id: int, user_id: str) -> HTTPResponse:
            res = await self.repo.get_resource_pool_users(
                keycloak_id=user_id, resource_pool_id=resource_pool_id, api_user=user
            )
            if len(res.allowed) > 0:
                return json(
                    apispec.PoolUserWithId(
                        id=res.allowed[0].keycloak_id, no_default_access=res.allowed[0].no_default_access
                    ).model_dump(exclude_none=True)
                )
            raise errors.MissingResourceError(
                message=f"The user with id {user_id} or resource pool with id {resource_pool_id} cannot be found."
            )

        return "/resource_pools/<resource_pool_id>/users/<user_id>", ["GET"], _get

    def delete(self) -> BlueprintFactoryResponse:
        """Remove access for a specific user to a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        @validate_db_ids
        async def _delete(
            _: Request, user: base_models.APIUser, resource_pool_id: int, user_id: str
        ) -> HTTPResponse | HTTPResponse:
            user_exists = await self.kc_user_repo.get_user(requested_by=user, id=user_id)
            if not user_exists:
                raise errors.MissingResourceError(message=f"The user with id {user_id} cannot be found.")
            resource_pools = await self.repo.get_user_resource_pools(
                api_user=user, keycloak_id=user_id, resource_pool_id=resource_pool_id
            )
            if len(resource_pools) == 0:
                return HTTPResponse(status=204)
            resource_pool = resource_pools[0]
            if resource_pool.default:
                await self.repo.update_user(api_user=user, keycloak_id=user_id, no_default_access=True)
            else:
                await self.repo.delete_resource_pool_user(
                    resource_pool_id=resource_pool_id, keycloak_id=user_id, api_user=user
                )
            return HTTPResponse(status=204)

        return "/resource_pools/<resource_pool_id>/users/<user_id>", ["DELETE"], _delete


@dataclass(kw_only=True)
class ClassesBP(CustomBlueprint):
    """Handlers for dealing with resource classes of an individual resource pool."""

    repo: ResourcePoolRepository
    authenticator: base_models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """Get the classes of a specific resource pool."""

        @authenticate(self.authenticator)
        @validate_db_ids
        async def _get_all(request: Request, user: base_models.APIUser, resource_pool_id: int) -> HTTPResponse:
            res = await self.repo.get_classes(
                api_user=user, resource_pool_id=resource_pool_id, name=request.args.get("name")
            )
            return json([apispec.ResourceClassWithId.model_validate(r).model_dump(exclude_none=True) for r in res])

        return "/resource_pools/<resource_pool_id>/classes", ["GET"], _get_all

    def post(self) -> BlueprintFactoryResponse:
        """Add a class to a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        @validate_db_ids
        @validate(json=apispec.ResourceClass)
        async def _post(
            _: Request, user: base_models.APIUser, body: apispec.ResourceClass, resource_pool_id: int
        ) -> HTTPResponse:
            cls = models.ResourceClass.from_dict(body.model_dump())
            res = await self.repo.insert_resource_class(
                api_user=user, resource_class=cls, resource_pool_id=resource_pool_id
            )
            return json(apispec.ResourceClassWithId.model_validate(res).model_dump(exclude_none=True), 201)

        return "/resource_pools/<resource_pool_id>/classes", ["POST"], _post

    def get(self) -> BlueprintFactoryResponse:
        """Get a specific class of a specific resource pool."""

        @authenticate(self.authenticator)
        @validate_db_ids
        async def _get(_: Request, user: base_models.APIUser, resource_pool_id: int, class_id: int) -> HTTPResponse:
            res = await self.repo.get_classes(api_user=user, resource_pool_id=resource_pool_id, id=class_id)
            if len(res) < 1:
                raise errors.MissingResourceError(
                    message=f"The class with id {class_id} or resource pool with id {resource_pool_id} cannot be found."
                )
            return json(apispec.ResourceClassWithId.model_validate(res[0]).model_dump(exclude_none=True))

        return "/resource_pools/<resource_pool_id>/classes/<class_id>", ["GET"], _get

    def get_no_pool(self) -> BlueprintFactoryResponse:
        """Get a specific class."""

        @authenticate(self.authenticator)
        @validate_db_ids
        async def _get_no_pool(_: Request, user: base_models.APIUser, class_id: int) -> HTTPResponse:
            res = await self.repo.get_classes(api_user=user, id=class_id)
            if len(res) < 1:
                raise errors.MissingResourceError(message=f"The class with id {class_id} cannot be found.")
            return json(apispec.ResourceClassWithId.model_validate(res[0]).model_dump(exclude_none=True))

        return "/classes/<class_id>", ["GET"], _get_no_pool

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific class from a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        @validate_db_ids
        async def _delete(_: Request, user: base_models.APIUser, resource_pool_id: int, class_id: int) -> HTTPResponse:
            await self.repo.delete_resource_class(
                api_user=user, resource_pool_id=resource_pool_id, resource_class_id=class_id
            )
            return HTTPResponse(status=204)

        return "/resource_pools/<resource_pool_id>/classes/<class_id>", ["DELETE"], _delete

    def put(self) -> BlueprintFactoryResponse:
        """Update all fields of a specific resource class for a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.ResourceClass)
        async def _put(
            _: Request, user: base_models.APIUser, body: apispec.ResourceClass, resource_pool_id: int, class_id: int
        ) -> HTTPResponse:
            res = await self.repo.update_resource_class(
                user, resource_pool_id, class_id, put=True, **body.model_dump(exclude_none=True)
            )
            return json(apispec.ResourceClassWithId.model_validate(res).model_dump(exclude_none=True))

        return "/resource_pools/<resource_pool_id>/classes/<class_id>", ["PUT"], _put

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update a specific resource class for a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.ResourceClassPatch)
        async def _patch(
            _: Request,
            user: base_models.APIUser,
            body: apispec.ResourceClassPatch,
            resource_pool_id: int,
            class_id: int,
        ) -> HTTPResponse:
            res = await self.repo.update_resource_class(
                user, resource_pool_id, class_id, put=False, **body.model_dump(exclude_none=True)
            )
            return json(apispec.ResourceClassWithId.model_validate(res).model_dump(exclude_none=True))

        return "/resource_pools/<resource_pool_id>/classes/<class_id>", ["PATCH"], _patch

    def get_tolerations(self) -> BlueprintFactoryResponse:
        """Get all tolerations of a resource class."""

        @authenticate(self.authenticator)
        @only_admins
        async def _get_tolerations(
            _: Request, user: base_models.APIUser, resource_pool_id: int, class_id: int
        ) -> HTTPResponse:
            res = await self.repo.get_tolerations(user, resource_pool_id, class_id)
            return json(list(res))

        return "/resource_pools/<resource_pool_id>/classes/<class_id>/tolerations", ["GET"], _get_tolerations

    def delete_tolerations(self) -> BlueprintFactoryResponse:
        """Delete all tolerations of a resource class."""

        @authenticate(self.authenticator)
        @only_admins
        async def _delete_tolerations(
            _: Request, user: base_models.APIUser, resource_pool_id: int, class_id: int
        ) -> HTTPResponse:
            await self.repo.delete_tolerations(user, resource_pool_id, class_id)
            return empty()

        return "/resource_pools/<resource_pool_id>/classes/<class_id>/tolerations", ["DELETE"], _delete_tolerations

    def get_affinities(self) -> BlueprintFactoryResponse:
        """Get all affinities of a resource class."""

        @authenticate(self.authenticator)
        @only_admins
        async def _get_affinities(
            _: Request, user: base_models.APIUser, resource_pool_id: int, class_id: int
        ) -> HTTPResponse:
            res = await self.repo.get_affinities(user, resource_pool_id, class_id)
            return json([apispec.NodeAffinity.model_validate(i).model_dump(exclude_none=True) for i in res])

        return "/resource_pools/<resource_pool_id>/classes/<class_id>/node_affinities", ["GET"], _get_affinities

    def delete_affinities(self) -> BlueprintFactoryResponse:
        """Delete all affinities of a resource class."""

        @authenticate(self.authenticator)
        @only_admins
        async def _delete_affinities(
            _: Request, user: base_models.APIUser, resource_pool_id: int, class_id: int
        ) -> HTTPResponse:
            await self.repo.delete_affinities(user, resource_pool_id, class_id)
            return empty()

        return "/resource_pools/<resource_pool_id>/classes/<class_id>/node_affinities", ["DELETE"], _delete_affinities


@dataclass(kw_only=True)
class QuotaBP(CustomBlueprint):
    """Handlers for dealing with a quota."""

    rp_repo: ResourcePoolRepository
    quota_repo: QuotaRepository
    authenticator: base_models.Authenticator

    def get(self) -> BlueprintFactoryResponse:
        """Get the quota for a specific resource pool."""

        @authenticate(self.authenticator)
        @validate_db_ids
        async def _get(_: Request, user: base_models.APIUser, resource_pool_id: int) -> HTTPResponse:
            rps = await self.rp_repo.get_resource_pools(api_user=user, id=resource_pool_id)
            if len(rps) < 1:
                raise errors.MissingResourceError(
                    message=f"The resource pool with ID {resource_pool_id} cannot be found."
                )
            rp = rps[0]
            if rp.quota is None:
                raise errors.MissingResourceError(
                    message=f"The resource pool with ID {resource_pool_id} does not have a quota."
                )
            return json(apispec.QuotaWithId.model_validate(rp.quota).model_dump(exclude_none=True))

        return "/resource_pools/<resource_pool_id>/quota", ["GET"], _get

    def put(self) -> BlueprintFactoryResponse:
        """Update all fields of a the quota of a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.QuotaWithId)
        async def _put(
            _: Request, user: base_models.APIUser, resource_pool_id: int, body: apispec.QuotaWithId
        ) -> HTTPResponse:
            return await self._put_patch(resource_pool_id, body, api_user=user)

        return "/resource_pools/<resource_pool_id>/quota", ["PUT"], _put

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update the quota of a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.QuotaPatch)
        async def _patch(
            _: Request, user: base_models.APIUser, resource_pool_id: int, body: apispec.QuotaPatch
        ) -> HTTPResponse:
            return await self._put_patch(resource_pool_id, body, api_user=user)

        return "/resource_pools/<resource_pool_id>/quota", ["PATCH"], _patch

    async def _put_patch(
        self, resource_pool_id: int, body: apispec.QuotaPatch | apispec.QuotaWithId, api_user: base_models.APIUser
    ) -> HTTPResponse:
        rps = await self.rp_repo.get_resource_pools(api_user=api_user, id=resource_pool_id)
        if len(rps) < 1:
            raise errors.MissingResourceError(message=f"Cannot find the resource pool with ID {resource_pool_id}.")
        rp = rps[0]
        if rp.quota is None:
            raise errors.MissingResourceError(
                message=f"The resource pool with ID {resource_pool_id} does not have a quota."
            )
        old_quota = rp.quota
        new_quota = models.Quota.from_dict({**asdict(old_quota), **body.model_dump(exclude_none=True)})
        for rc in rp.classes:
            if not new_quota.is_resource_class_compatible(rc):
                raise errors.ValidationError(
                    message=f"The quota {new_quota} is not compatible with the resource class {rc}."
                )
        new_quota = self.quota_repo.update_quota(new_quota)
        return json(apispec.QuotaWithId.model_validate(new_quota).model_dump(exclude_none=True))


@dataclass(kw_only=True)
class UserResourcePoolsBP(CustomBlueprint):
    """Handlers for dealing with the resource pools of a specific user."""

    repo: UserRepository
    kc_user_repo: KcUserRepo
    authenticator: base_models.Authenticator

    def get(self) -> BlueprintFactoryResponse:
        """Get all resource pools that a specific user has access to."""

        @authenticate(self.authenticator)
        @only_admins
        async def _get(_: Request, user: base_models.APIUser, user_id: str) -> HTTPResponse:
            rps = await self.repo.get_user_resource_pools(keycloak_id=user_id, api_user=user)
            return json([apispec.ResourcePoolWithId.model_validate(rp).model_dump(exclude_none=True) for rp in rps])

        return "/users/<user_id>/resource_pools", ["GET"], _get

    def post(self) -> BlueprintFactoryResponse:
        """Give a specific user access to a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        async def _post(request: Request, user: base_models.APIUser, user_id: str) -> HTTPResponse:
            ids = apispec.IntegerIds.model_validate(request.json)  # validation
            return await self._post_put(user_id=user_id, post=True, resource_pool_ids=ids, api_user=user)

        return "/users/<user_id>/resource_pools", ["POST"], _post

    def put(self) -> BlueprintFactoryResponse:
        """Set the list of resource pools that a specific user has access to."""

        @authenticate(self.authenticator)
        @only_admins
        async def _put(request: Request, user: base_models.APIUser, user_id: str) -> HTTPResponse:
            ids = apispec.IntegerIds.model_validate(request.json)  # validation
            return await self._post_put(user_id=user_id, post=False, resource_pool_ids=ids, api_user=user)

        return "/users/<user_id>/resource_pools", ["PUT"], _put

    async def _post_put(
        self, user_id: str, resource_pool_ids: apispec.IntegerIds, api_user: base_models.APIUser, post: bool = True
    ) -> HTTPResponse:
        user_check = await self.kc_user_repo.get_user(requested_by=api_user, id=user_id)
        if not user_check:
            raise errors.MissingResourceError(message=f"User with user ID {user_id} cannot be found")
        rps = await self.repo.update_user_resource_pools(
            keycloak_id=user_id, resource_pool_ids=resource_pool_ids.root, append=post, api_user=api_user
        )
        return json([apispec.ResourcePoolWithId.model_validate(rp).model_dump(exclude_none=True) for rp in rps])
