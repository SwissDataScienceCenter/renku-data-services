"""Compute resource access control (CRAC) app."""
import asyncio
from dataclasses import dataclass
from typing import Any, Dict

from sanic import HTTPResponse, Request, Sanic, json
from sanic_ext import validate

import models
from db.adapter import ResourcePoolRepository, UserRepository
from models import errors
from renku_crac.auth import authenticate, only_admins
from renku_crac.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_crac.config import Config
from renku_crac.error_handler import CustomErrorHandler
from schemas import apispec


@dataclass(kw_only=True)
class ResourcePoolsBP(CustomBlueprint):
    """Handlers for manipulating resource pools."""

    rp_repo: ResourcePoolRepository
    user_repo: UserRepository
    authenticator: models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """List all resource pools."""

        @authenticate(self.authenticator)
        async def _get_all(_: Request, user: models.APIUser):
            res = await self.rp_repo.get_resource_pools(api_user=user)
            return json([apispec.ResourcePoolWithId.from_orm(r).dict(exclude_none=True) for r in res])

        return "/resource_pools", ["GET"], _get_all

    def post(self) -> BlueprintFactoryResponse:
        """Add a new resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.ResourcePool)
        async def _post(_: Request, body: apispec.ResourcePool, user: models.APIUser):
            rp = models.ResourcePool.from_dict(body.dict())
            res = await self.rp_repo.insert_resource_pool(api_user=user, resource_pool=rp)
            return json(apispec.ResourcePoolWithId.from_orm(res).dict(exclude_none=True), 201)

        return "/resource_pools", ["POST"], _post

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific resource pool."""

        @authenticate(self.authenticator)
        async def _get_one(request: Request, resource_pool_id: int, user: models.APIUser):
            res = await self.rp_repo.get_resource_pools(
                api_user=user, id=resource_pool_id, name=request.args.get("name")
            )
            if len(res) < 1:
                raise errors.MissingResourceError(
                    message=f"The resource pool with id {resource_pool_id} cannot be found."
                )
            return json(apispec.ResourcePoolWithId.from_orm(res[0]).dict(exclude_none=True))

        return "/resource_pools/<resource_pool_id>", ["GET"], _get_one

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        async def _delete(_: Request, resource_pool_id: int, user: models.APIUser):
            await self.rp_repo.delete_resource_pool(api_user=user, id=resource_pool_id)
            return HTTPResponse(status=204)

        return "/resource_pools/<resource_pool_id>", ["DELETE"], _delete

    def put(self) -> BlueprintFactoryResponse:
        """Update all fields of a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.ResourcePoolPut)
        async def _put(_: Request, resource_pool_id: int, body: apispec.ResourcePoolPut, user: models.APIUser):
            return await self._put_patch_resource_pool(api_user=user, resource_pool_id=resource_pool_id, body=body)

        return "/resource_pools/<resource_pool_id>", ["PUT"], _put

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.ResourcePoolPatch)
        async def _patch(_: Request, resource_pool_id: int, body: apispec.ResourcePoolPatch, user: models.APIUser):
            return await self._put_patch_resource_pool(api_user=user, resource_pool_id=resource_pool_id, body=body)

        return "/resource_pools/<resource_pool_id>", ["PATCH"], _patch

    async def _put_patch_resource_pool(
        self, api_user: models.APIUser, resource_pool_id: int, body: apispec.ResourcePoolPut | apispec.ResourcePoolPatch
    ):
        res = await self.rp_repo.update_resource_pool(
            api_user=api_user, id=resource_pool_id, **body.dict(exclude_none=True)
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
            users = apispec.UsersWithId.parse_obj(request.json)  # validation
            return await self._put_post(api_user=user, resource_pool_id=resource_pool_id, body=users, post=True)

        return "/resource_pools/<resource_pool_id>/users", ["POST"], _post

    def put(self) -> BlueprintFactoryResponse:
        """Set the users for a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        async def _put(request: Request, resource_pool_id: int, user: models.APIUser):
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
            res = await self.repo.get_classes(api_user=user, resource_pool_id=resource_pool_id, id=class_id)
            if len(res) < 1:
                raise errors.MissingResourceError(
                    message=f"The class with id {class_id} or resource pool with id {resource_pool_id} cannot be found."
                )
            return json(apispec.ResourceClassWithId.from_orm(res[0]).dict(exclude_none=True))

        return "/resource_pools/<resource_pool_id>/classes/<class_id>", ["GET"], _get

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific class from a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        async def _delete(_: Request, resource_pool_id: int, class_id: int, user: models.APIUser):
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

    repo: ResourcePoolRepository
    authenticator: models.Authenticator

    def get(self) -> BlueprintFactoryResponse:
        """Get the quota for a specific resource pool."""

        @authenticate(self.authenticator)
        async def _get(_: Request, resource_pool_id: int, user: models.APIUser):
            res = await self.repo.get_quota(resource_pool_id=resource_pool_id, api_user=user)
            if res is None:
                raise errors.MissingResourceError(
                    message=f"The quota for the resource pool with ID {resource_pool_id} cannot be found."
                )
            return json(apispec.Resources.from_orm(res).dict(exclude_none=True))

        return "/resource_pools/<resource_pool_id>/quota", ["GET"], _get

    def put(self) -> BlueprintFactoryResponse:
        """Update all fields of a the quota of a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.Resources)
        async def _put(_: Request, resource_pool_id: int, body: apispec.Resources, user: models.APIUser):
            return await self._put_patch(resource_pool_id, body, api_user=user)

        return "/resource_pools/<resource_pool_id>/quota", ["PUT"], _put

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update the quota of a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.ResourcesPatch)
        async def _patch(_: Request, resource_pool_id: int, body: apispec.ResourcesPatch, user: models.APIUser):
            return await self._put_patch(resource_pool_id, body, api_user=user)

        return "/resource_pools/<resource_pool_id>/quota", ["PATCH"], _patch

    async def _put_patch(
        self, resource_pool_id: int, body: apispec.ResourcesPatch | apispec.Resources, api_user: models.APIUser
    ):
        res = await self.repo.update_quota(
            resource_pool_id=resource_pool_id, api_user=api_user, **body.dict(exclude_none=True)
        )
        if res is None:
            raise errors.MissingResourceError(
                message=f"The quota or the resource pool with ID {resource_pool_id} cannot be found."
            )
        return json(apispec.Resources.from_orm(res).dict(exclude_none=True))


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
            if user.access_token is None:
                raise errors.Unauthorized()
            users_db, user_kc = await asyncio.gather(
                self.repo.get_users(keycloak_id=body.id, api_user=user),
                self.user_store.get_user_by_id(body.id, user.access_token),
            )
            user_db = users_db[0] if len(users_db) >= 1 else None
            # The user does not exist in keycloak, delete it form the crac database and fail.
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
            res = await self.repo.get_users(api_user=user)
            return json([apispec.UserWithId(id=r.keycloak_id).dict(exclude_none=True) for r in res])

        return "/users", ["GET"], _get_all

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific user, removing them from any resource pool they had access to."""

        @authenticate(self.authenticator)
        @only_admins
        async def _delete(_: Request, user_id: str, user: models.APIUser):
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
            rps = await self.repo.get_user_resource_pools(keycloak_id=user_id, api_user=user)
            return json([apispec.ResourcePoolWithId.from_orm(rp).dict(exclude_none=True) for rp in rps])

        return "/users/<user_id>/resource_pools", ["GET"], _get

    def post(self) -> BlueprintFactoryResponse:
        """Give a specific user access to a specific resource pool."""

        @authenticate(self.authenticator)
        @only_admins
        async def _post(request: Request, user_id: str, user: models.APIUser):
            ids = apispec.IntegerIds.parse_obj(request.json)  # validation
            return await self._post_put(user_id=user_id, post=True, resource_pool_ids=ids, api_user=user)

        return "/users/<user_id>/resource_pools", ["POST"], _post

    def put(self) -> BlueprintFactoryResponse:
        """Set the list of resource pools that a specific user has access to."""

        @authenticate(self.authenticator)
        @only_admins
        async def _put(request: Request, user_id: str, user: models.APIUser):
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
    """Server contains all handlers for CRAC and the configuration."""

    apispec: Dict[str, Any]
    version: str

    def get_apispec(self) -> BlueprintFactoryResponse:
        """Servers the OpenAPI specification."""

        async def _get_apispec(_: Request):
            return json(self.apispec)

        return "/spec.json", ["GET"], _get_apispec

    def get_error(self) -> BlueprintFactoryResponse:
        """Returns a sample error response."""

        async def _get_error(_: Request):
            raise errors.ValidationError(message="Sample validation error")

        return "/error", ["GET"], _get_error

    def get_version(self) -> BlueprintFactoryResponse:
        """Returns the version."""

        async def _get_version(_: Request):
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
    )
    classes = ClassesBP(name="classes", url_prefix=url_prefix, repo=config.rp_repo, authenticator=config.authenticator)
    quota = QuotaBP(name="quota", url_prefix=url_prefix, repo=config.rp_repo, authenticator=config.authenticator)
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
