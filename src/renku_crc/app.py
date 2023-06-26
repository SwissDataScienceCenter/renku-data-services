"""Compute resource control (CRC) app."""
import asyncio
from dataclasses import asdict, dataclass
from typing import Any, Dict, List

from sanic import HTTPResponse, Request, Sanic, json
from sanic_ext import validate

import models
from db.adapter import ResourcePoolRepository, UserRepository
from k8s.quota import QuotaRepository
from models import errors
from renku_crc.auth import authenticate, only_admins
from renku_crc.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_crc.config import Config
from renku_crc.error_handler import CustomErrorHandler
from schemas import apispec

from prometheus_client import Counter

c = Counter('my_requests', 'The number of times my API was accessed', ['method', 'endpoint'])

@dataclass(kw_only=True)
class ResourcePoolsBP(CustomBlueprint):
    """Handlers for manipulating resource pools."""

    rp_repo: ResourcePoolRepository
    user_repo: UserRepository
    authenticator: models.Authenticator
    quota_repo: QuotaRepository

    def get_all(self) -> BlueprintFactoryResponse:
        """List all resource pools."""

        @authenticate(self.authenticator)
        async def _get_all(_: Request, user: models.APIUser):
            c.labels('GET', '/resource_pools').inc()
            pool = asyncio.get_running_loop()
            rps: List[models.ResourcePool]
            quotas: List[models.Quota]
            rps, quotas = await asyncio.gather(
                self.rp_repo.get_resource_pools(api_user=user),
                pool.run_in_executor(None, self.quota_repo.get_quotas),
            )
            quotas_dict = {quota.id: quota for quota in quotas}
            rps_w_quota: List[models.ResourcePool] = []
            for rp in rps:
                quota = quotas_dict.get(rp.quota) if isinstance(rp.quota, str) else None
                if quota is not None:
                    rp_w_quota = rp.set_quota(quota)
                    rps_w_quota.append(rp_w_quota)
                else:
                    rps_w_quota.append(rp)

            return json([apispec.ResourcePoolWithId.from_orm(r).dict(exclude_none=True) for r in rps_w_quota])
        return "/resource_pools", ["GET"], _get_all

    def post(self) -> BlueprintFactoryResponse:
        """Add a new resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.ResourcePool)
        async def _post(_: Request, body: apispec.ResourcePool, user: models.APIUser):
            c.labels('POST', '/resource_pools').inc()
            rp = models.ResourcePool.from_dict(body.dict())
            if not isinstance(rp.quota, models.Quota):
                raise errors.ValidationError(message="The quota in the resource pool is malformed.")
            quota_with_id = rp.quota.generate_id()
            rp = rp.set_quota(quota_with_id)
            self.quota_repo.create_quota(quota_with_id)
            res = await self.rp_repo.insert_resource_pool(api_user=user, resource_pool=rp)
            res = res.set_quota(quota_with_id)
            return json(apispec.ResourcePoolWithId.from_orm(res).dict(exclude_none=True), 201)

        return "/resource_pools", ["POST"], _post

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific resource pool."""

        @authenticate(self.authenticator)
        async def _get_one(request: Request, resource_pool_id: int, user: models.APIUser):
            c.labels('GET', '/resource_pools/:resource_pool_id').inc()
            pool = asyncio.get_running_loop()
            rps: List[models.ResourcePool]
            quotas: List[models.Quota]
            rps, quotas = await asyncio.gather(
                self.rp_repo.get_resource_pools(api_user=user, id=resource_pool_id, name=request.args.get("name")),
                pool.run_in_executor(None, self.quota_repo.get_quotas),
            )
            if len(rps) < 1:
                raise errors.MissingResourceError(
                    message=f"The resource pool with id {resource_pool_id} cannot be found."
                )
            rp = rps[0]
            quotas = [i for i in quotas if i.id == rp.quota]
            if len(quotas) >= 1:
                quota = quotas[0]
                rp = rp.set_quota(quota)
            return json(apispec.ResourcePoolWithId.from_orm(rp).dict(exclude_none=True))

        return "/resource_pools/<resource_pool_id>", ["GET"], _get_one

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        async def _delete(_: Request, resource_pool_id: int, user: models.APIUser):
            c.labels('DELETE', '/resource_pools/:resource_pool_id').inc()
            rp = await self.rp_repo.delete_resource_pool(api_user=user, id=resource_pool_id)
            if rp is not None and isinstance(rp.quota, str):
                self.quota_repo.delete_quota(rp.quota)
            return HTTPResponse(status=204)

        return "/resource_pools/<resource_pool_id>", ["DELETE"], _delete

    def put(self) -> BlueprintFactoryResponse:
        """Update all fields of a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.ResourcePoolPut)
        async def _put(_: Request, resource_pool_id: int, body: apispec.ResourcePoolPut, user: models.APIUser):
            c.labels('PUT', '/resource_pools/:resource_pool_id').inc()
            return await self._put_patch_resource_pool(api_user=user, resource_pool_id=resource_pool_id, body=body)

        return "/resource_pools/<resource_pool_id>", ["PUT"], _put

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.ResourcePoolPatch)
        async def _patch(_: Request, resource_pool_id: int, body: apispec.ResourcePoolPatch, user: models.APIUser):
            c.labels('PATCH', '/resource_pools/:resource_pool_id').inc()
            return await self._put_patch_resource_pool(api_user=user, resource_pool_id=resource_pool_id, body=body)

        return "/resource_pools/<resource_pool_id>", ["PATCH"], _patch

    async def _put_patch_resource_pool(
        self, api_user: models.APIUser, resource_pool_id: int, body: apispec.ResourcePoolPut | apispec.ResourcePoolPatch
    ):
        c.labels('PUT', '/resource_pools/:resource_pool_id').inc()
        body_dict = body.dict(exclude_none=True)
        quota_req = body_dict.pop("quota", None)
        if quota_req is not None:
            rps = await self.rp_repo.get_resource_pools(api_user, resource_pool_id)
            if len(rps) == 0:
                raise errors.ValidationError(message=f"The resource pool with ID {resource_pool_id} does not exist.")
            rp = rps[0]
            if isinstance(rp.quota, str):
                quota_req["id"] = rp.quota
            quota_model = models.Quota.from_dict(quota_req)
            if quota_model.id is None:
                quota_model = quota_model.generate_id()
            self.quota_repo.update_quota(quota_model)
            if rp.quota is None:
                body_dict["quota"] = quota_model.id
        res = await self.rp_repo.update_resource_pool(
            api_user=api_user,
            id=resource_pool_id,
            **body_dict,
        )
        if res is None:
            raise errors.MissingResourceError(message=f"The resource pool with ID {resource_pool_id} cannot be found.")
        return json(apispec.ResourcePoolWithId.from_orm(res).dict(exclude_none=True))


@dataclass(kw_only=True)
class ResourcePoolUsersBP(CustomBlueprint):
    """Handlers for dealing with the users of individual resource pools."""

    repo: UserRepository
    authenticator: models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """Get all users of a specific resource pool."""

        c.labels('GET', '/resource_pools/:resource_pool_id/users').inc()
        @authenticate(self.authenticator)
        @only_admins
        async def _get_all(_: Request, resource_pool_id: int, user: models.APIUser):
            res = await self.repo.get_users(api_user=user, resource_pool_id=resource_pool_id)
            return json([apispec.UserWithId(id=r.keycloak_id).dict(exclude_none=True) for r in res])

        return "/resource_pools/<resource_pool_id>/users", ["GET"], _get_all

    def post(self) -> BlueprintFactoryResponse:
        """Add users to a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        async def _post(request: Request, resource_pool_id: int, user: models.APIUser):
            c.labels('POST', '/resource_pools/:resource_pool_id/users').inc()
            users = apispec.UsersWithId.parse_obj(request.json)  # validation
            return await self._put_post(api_user=user, resource_pool_id=resource_pool_id, body=users, post=True)

        return "/resource_pools/<resource_pool_id>/users", ["POST"], _post

    def put(self) -> BlueprintFactoryResponse:
        """Set the users for a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        async def _put(request: Request, resource_pool_id: int, user: models.APIUser):
            c.labels('PUT', '/resource_pools/:resource_pool_id/users').inc()
            users = apispec.UsersWithId.parse_obj(request.json)  # validation
            return await self._put_post(api_user=user, resource_pool_id=resource_pool_id, body=users, post=False)

        return "/resource_pools/<resource_pool_id>/users", ["PUT"], _put

    async def _put_post(
        self, api_user: models.APIUser, resource_pool_id: int, body: apispec.UsersWithId, post: bool = True
    ):
        users_to_add = [models.User(keycloak_id=user.id) for user in body.__root__]
        updated_users = await self.repo.update_resource_pool_users(
            api_user=api_user, resource_pool_id=resource_pool_id, users=users_to_add, append=post
        )
        return json(
            [apispec.UserWithId(id=r.keycloak_id).dict(exclude_none=True) for r in updated_users],
            status=201 if post else 200,
        )

    def get(self) -> BlueprintFactoryResponse:
        """Get a specific user of a specific resource pool."""

        @authenticate(self.authenticator)
        async def _get(_: Request, resource_pool_id: int, user_id: str, user: models.APIUser):
            c.labels('GET', '/resource_pools/:resource_pool_id/users/:user_id').inc()
            res = await self.repo.get_users(keycloak_id=user_id, resource_pool_id=resource_pool_id, api_user=user)
            if len(res) < 1:
                raise errors.MissingResourceError(
                    message=f"The user with id {user_id} or resource pool with id {resource_pool_id} cannot be found."
                )
            return json(apispec.UserWithId(id=res[0].keycloak_id).dict(exclude_none=True))

        return "/resource_pools/<resource_pool_id>/users/<user_id>", ["GET"], _get

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific user of a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        async def _delete(_: Request, resource_pool_id: int, user_id: str, user: models.APIUser):
            c.labels('DELETE', '/resource_pools/:resource_pool_id/users/:user_id').inc()
            await self.repo.delete_resource_pool_user(
                resource_pool_id=resource_pool_id, keycloak_id=user_id, api_user=user
            )
            return HTTPResponse(status=204)

        return "/resource_pools/<resource_pool_id>/users/<user_id>", ["DELETE"], _delete


@dataclass(kw_only=True)
class ClassesBP(CustomBlueprint):
    """Handlers for dealing with resource classes of an individual resource pool."""

    repo: ResourcePoolRepository
    authenticator: models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """Get the classes of a specific resource pool."""

        @authenticate(self.authenticator)
        async def _get_all(request: Request, resource_pool_id: int, user: models.APIUser):
            c.labels('GET', '/resource_pools/:resource_pool_id/classes').inc()
            res = await self.repo.get_classes(
                api_user=user, resource_pool_id=resource_pool_id, name=request.args.get("name")
            )
            return json([apispec.ResourceClassWithId.from_orm(r).dict(exclude_none=True) for r in res])

        return "/resource_pools/<resource_pool_id>/classes", ["GET"], _get_all

    def post(self) -> BlueprintFactoryResponse:
        """Add a class to a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.ResourceClass)
        async def _post(_: Request, body: apispec.ResourceClass, resource_pool_id: int, user: models.APIUser):
            c.labels('POST', '/resource_pools/:resource_pool_id/classes').inc()
            cls = models.ResourceClass.from_dict(body.dict())
            res = await self.repo.insert_resource_class(
                api_user=user, resource_class=cls, resource_pool_id=resource_pool_id
            )
            return json(apispec.ResourceClassWithId.from_orm(res).dict(exclude_none=True), 201)

        return "/resource_pools/<resource_pool_id>/classes", ["POST"], _post

    def get(self) -> BlueprintFactoryResponse:
        """Get a specific class of a specific resource pool."""

        @authenticate(self.authenticator)
        async def _get(_: Request, resource_pool_id: int, class_id: int, user: models.APIUser):
            c.labels('GET', '/resource_pools/:resource_pool_id/classes/:class_id').inc()
            res = await self.repo.get_classes(api_user=user, resource_pool_id=resource_pool_id, id=class_id)
            if len(res) < 1:
                raise errors.MissingResourceError(
                    message=f"The class with id {class_id} or resource pool with id {resource_pool_id} cannot be found."
                )
            return json(apispec.ResourceClassWithId.from_orm(res[0]).dict(exclude_none=True))

        return "/resource_pools/<resource_pool_id>/classes/<class_id>", ["GET"], _get

    def get_no_pool(self) -> BlueprintFactoryResponse:
        """Get a specific class."""

        @authenticate(self.authenticator)
        async def _get_no_pool(_: Request, class_id: int, user: models.APIUser):
            c.labels('GET', '/classes/:class_id').inc()
            res = await self.repo.get_classes(api_user=user, id=class_id)
            if len(res) < 1:
                raise errors.MissingResourceError(message=f"The class with id {class_id} cannot be found.")
            return json(apispec.ResourceClassWithId.from_orm(res[0]).dict(exclude_none=True))

        return "/classes/<class_id>", ["GET"], _get_no_pool

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific class from a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        async def _delete(_: Request, resource_pool_id: int, class_id: int, user: models.APIUser):
            c.labels('DELETE', '/resource_pools/:resource_pool_id/classes/:class_id').inc()
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
            _: Request, body: apispec.ResourceClass, resource_pool_id: int, class_id: int, user: models.APIUser
        ):
            return await self._put_patch(user, resource_pool_id, class_id, body)

        c.labels('PUT', '/resource_pools/:resource_pool_id/classes/:class_id').inc()

        return "/resource_pools/<resource_pool_id>/classes/<class_id>", ["PUT"], _put

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update a specific resource class for a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.ResourceClassPatch)
        async def _patch(
            _: Request, body: apispec.ResourceClassPatch, resource_pool_id: int, class_id: int, user: models.APIUser
        ):
            return await self._put_patch(user, resource_pool_id, class_id, body)

        c.labels('PATCH', '/resource_pools/:resource_pool_id/classes/:class_id').inc()

        return "/resource_pools/<resource_pool_id>/classes/<class_id>", ["PATCH"], _patch

    async def _put_patch(
        self,
        api_user: models.APIUser,
        resource_pool_id: int,
        class_id: int,
        body: apispec.ResourceClassPatch | apispec.ResourceClass,
    ):
        cls = await self.repo.update_resource_class(
            api_user=api_user,
            resource_pool_id=resource_pool_id,
            resource_class_id=class_id,
            **body.dict(exclude_none=True),
        )
        return json(apispec.ResourceClassWithId.from_orm(cls).dict(exclude_none=True))


@dataclass(kw_only=True)
class QuotaBP(CustomBlueprint):
    """Handlers for dealing with a quota."""

    rp_repo: ResourcePoolRepository
    quota_repo: QuotaRepository
    authenticator: models.Authenticator

    def get(self) -> BlueprintFactoryResponse:
        """Get the quota for a specific resource pool."""

        @authenticate(self.authenticator)
        async def _get(_: Request, resource_pool_id: int, user: models.APIUser):
            c.labels('GET', '/resource_pools/:resource_pool_id/quota').inc()
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
            if not isinstance(rp.quota, str):
                raise errors.ValidationError(message="The quota in the resource pool should be a string.")
            quotas = self.quota_repo.get_quotas(name=rp.quota)
            if len(quotas) < 1:
                raise errors.MissingResourceError(
                    message=f"Cannot find the quota with name {rp.quota} "
                    f"for the resource pool with ID {resource_pool_id}."
                )
            quota = quotas[0]
            return json(apispec.QuotaWithId.from_orm(quota).dict(exclude_none=True))

        return "/resource_pools/<resource_pool_id>/quota", ["GET"], _get

    def put(self) -> BlueprintFactoryResponse:
        """Update all fields of a the quota of a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.Quota)
        async def _put(_: Request, resource_pool_id: int, body: apispec.QuotaWithId, user: models.APIUser):
            c.labels('PUT', '/resource_pools/:resource_pool_id/quota').inc()
            return await self._put_patch(resource_pool_id, body, api_user=user)

        return "/resource_pools/<resource_pool_id>/quota", ["PUT"], _put

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update the quota of a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.QuotaPatch)
        async def _patch(_: Request, resource_pool_id: int, body: apispec.QuotaPatch, user: models.APIUser):
            c.labels('PATCH', '/resource_pools/:resource_pool_id/quota').inc()
            return await self._put_patch(resource_pool_id, body, api_user=user)

        return "/resource_pools/<resource_pool_id>/quota", ["PATCH"], _patch

    async def _put_patch(
        self, resource_pool_id: int, body: apispec.QuotaPatch | apispec.QuotaWithId, api_user: models.APIUser
    ):
        rps = await self.rp_repo.get_resource_pools(api_user=api_user, id=resource_pool_id)
        if len(rps) < 1:
            raise errors.MissingResourceError(message=f"Cannot find the resource pool with ID {resource_pool_id}.")
        rp = rps[0]
        if rp.quota is None:
            raise errors.MissingResourceError(
                message=f"The resource pool with ID {resource_pool_id} does not have a quota."
            )
        if not isinstance(rp.quota, str):
            raise errors.ValidationError(message="The quota in the resource pool should be a string.")
        quotas = self.quota_repo.get_quotas(name=rp.quota)
        if len(quotas) < 1:
            raise errors.MissingResourceError(
                message=f"Cannot find the quota with name {rp.quota} for the resource pool with ID {resource_pool_id}."
            )
        old_quota = quotas[0]
        new_quota = models.Quota.from_dict({**asdict(old_quota, **body.dict(exclude_none=True))})
        await self.quota_repo.update_quota(new_quota)
        return json(apispec.QuotaWithId.from_orm(new_quota).dict(exclude_none=True))


@dataclass(kw_only=True)
class UsersBP(CustomBlueprint):
    """Handlers for creating and listing users."""

    repo: UserRepository
    user_store: models.UserStore
    authenticator: models.Authenticator

    def post(self) -> BlueprintFactoryResponse:
        """Add a new user. The user has to exist in Keycloak."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.UserWithId)
        async def _post(request: Request, body: apispec.UserWithId, user: models.APIUser):
            c.labels('POST', '/users').inc()
            users_db, user_kc = await asyncio.gather(
                self.repo.get_users(keycloak_id=body.id, api_user=user),
                self.user_store.get_user_by_id(body.id, user.access_token),  # type: ignore[arg-type]
            )
            user_db = next(iter(users_db), None)
            # The user does not exist in keycloak, delete it form the crc database and fail.
            if user_kc is None:
                await self.repo.delete_user(id=body.id, api_user=user)
                raise errors.MissingResourceError(message=f"User with id {body.id} cannot be found in keycloak.")
            # The user exists in keycloak, fail if the requestd id does not match what is in keycloak.
            if body.id != user_kc.keycloak_id:
                raise errors.ValidationError(message="The provided user ID does not match the ID from keycloak.")
            # The user exists in the db and the request body matches what is the in the db, simply return the user.
            if user_db is not None and user_db.keycloak_id == body.id:
                return json(
                    apispec.UserWithId(id=user_db.keycloak_id).dict(exclude_none=True),
                    200,
                )
            # The user does not exist in the db, add it.
            kc_user = await self.repo.insert_user(api_user=user, user=models.User(keycloak_id=body.id))
            return json(
                apispec.UserWithId(id=kc_user.keycloak_id).dict(exclude_none=True),
                201,
            )

        return "/users", ["POST"], _post

    def get_all(self) -> BlueprintFactoryResponse:
        """Get all users. Please note that this is a subset of the users from Keycloak."""

        @authenticate(self.authenticator)
        @only_admins
        async def _get_all(_: Request, user: models.APIUser):
            c.labels('GET', '/users').inc()
            res = await self.repo.get_users(api_user=user)
            return json([apispec.UserWithId(id=r.keycloak_id).dict(exclude_none=True) for r in res])

        return "/users", ["GET"], _get_all

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific user, removing them from any resource pool they had access to."""

        @authenticate(self.authenticator)
        @only_admins
        async def _delete(_: Request, user_id: str, user: models.APIUser):
            c.labels('DELETE', '/users/:user_id').inc()
            await self.repo.delete_user(id=user_id, api_user=user)
            return HTTPResponse(status=204)

        return "/users/<user_id>", ["DELETE"], _delete


@dataclass(kw_only=True)
class UserResourcePoolsBP(CustomBlueprint):
    """Handlers for dealing wiht the resource pools of a specific user."""

    repo: UserRepository
    authenticator: models.Authenticator

    def get(self) -> BlueprintFactoryResponse:
        """Get all resource pools that a specific user has access to."""

        @authenticate(self.authenticator)
        @only_admins
        async def _get(_: Request, user_id: str, user: models.APIUser):
            c.labels('GET', '/users/:user_id/resource_pools').inc()
            rps = await self.repo.get_user_resource_pools(keycloak_id=user_id, api_user=user)
            return json([apispec.ResourcePoolWithId.from_orm(rp).dict(exclude_none=True) for rp in rps])

        return "/users/<user_id>/resource_pools", ["GET"], _get

    def post(self) -> BlueprintFactoryResponse:
        """Give a specific user access to a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        async def _post(request: Request, user_id: str, user: models.APIUser):
            c.labels('POST', '/users/:user_id/resource_pools').inc()
            ids = apispec.IntegerIds.parse_obj(request.json)  # validation
            return await self._post_put(user_id=user_id, post=True, resource_pool_ids=ids, api_user=user)

        return "/users/<user_id>/resource_pools", ["POST"], _post

    def put(self) -> BlueprintFactoryResponse:
        """Set the list of resource pools that a specific user has access to."""

        @authenticate(self.authenticator)
        @only_admins
        async def _put(request: Request, user_id: str, user: models.APIUser):
            c.labels('PUT', '/users/:user_id/resource_pools').inc()
            ids = apispec.IntegerIds.parse_obj(request.json)  # validation
            return await self._post_put(user_id=user_id, post=False, resource_pool_ids=ids, api_user=user)

        return "/users/<user_id>/resource_pools", ["PUT"], _put

    async def _post_put(
        self, user_id: str, resource_pool_ids: apispec.IntegerIds, api_user: models.APIUser, post: bool = True
    ):
        rps = await self.repo.update_user_resource_pools(
            keycloak_id=user_id, resource_pool_ids=resource_pool_ids.__root__, append=post, api_user=api_user
        )
        return json([apispec.ResourcePoolWithId.from_orm(rp).dict(exclude_none=True) for rp in rps])


@dataclass(kw_only=True)
class MiscBP(CustomBlueprint):
    """Server contains all handlers for CRC and the configuration."""

    apispec: Dict[str, Any]
    version: str

    def get_apispec(self) -> BlueprintFactoryResponse:
        """Servers the OpenAPI specification."""

        async def _get_apispec(_: Request):
            c.labels('GET', '/spec.json').inc()
            return json(self.apispec)

        return "/spec.json", ["GET"], _get_apispec

    def get_error(self) -> BlueprintFactoryResponse:
        """Returns a sample error response."""

        async def _get_error(_: Request):
            c.labels('GET', '/error').inc()
            raise errors.ValidationError(message="Sample validation error")

        return "/error", ["GET"], _get_error

    def get_version(self) -> BlueprintFactoryResponse:
        """Returns the version."""

        async def _get_version(_: Request):
            c.labels('GET', '/version').inc()
            return json({"version": self.version})

        return "/version", ["GET"], _get_version


def register_all_handlers(app: Sanic, config: Config) -> Sanic:
    """Register all handlers on the application."""
    url_prefix = "/api/data"
    resource_pools = ResourcePoolsBP(
        name="resource_pools",
        url_prefix=url_prefix,
        rp_repo=config.rp_repo,
        authenticator=config.authenticator,
        user_repo=config.user_repo,
        quota_repo=config.quota_repo,
    )
    classes = ClassesBP(name="classes", url_prefix=url_prefix, repo=config.rp_repo, authenticator=config.authenticator)
    quota = QuotaBP(
        name="quota",
        url_prefix=url_prefix,
        rp_repo=config.rp_repo,
        authenticator=config.authenticator,
        quota_repo=config.quota_repo,
    )
    resource_pools_users = ResourcePoolUsersBP(
        name="resource_pool_users", url_prefix=url_prefix, repo=config.user_repo, authenticator=config.authenticator
    )
    users = UsersBP(
        name="users",
        url_prefix=url_prefix,
        repo=config.user_repo,
        user_store=config.user_store,
        authenticator=config.authenticator,
    )
    user_resource_pools = UserResourcePoolsBP(
        name="user_resource_pools", url_prefix=url_prefix, repo=config.user_repo, authenticator=config.authenticator
    )
    misc = MiscBP(name="misc", url_prefix=url_prefix, apispec=config.spec, version=config.version)
    app.blueprint(
        [
            resource_pools.blueprint(),
            classes.blueprint(),
            quota.blueprint(),
            resource_pools_users.blueprint(),
            users.blueprint(),
            user_resource_pools.blueprint(),
            misc.blueprint(),
        ]
    )

    app.error_handler = CustomErrorHandler()
    app.config.OAS = False
    app.config.OAS_UI_REDOC = False
    app.config.OAS_UI_SWAGGER = False
    app.config.OAS_AUTODOC = False
    return app
