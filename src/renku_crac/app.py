"""Compute resource access control (CRAC) app."""
import asyncio
from dataclasses import dataclass
from typing import Any, Dict

from sanic import HTTPResponse, Request, Sanic, json
from sanic.views import HTTPMethodView
from sanic_ext import validate

from src import models
from src.db.adapter import ResourcePoolRepository, UserRepository
from src.models import errors
from src.renku_crac.config import Config
from src.renku_crac.error_handler import CustomErrorHandler
from src.schemas import apispec


@dataclass
class ResourcePoolsView(HTTPMethodView):
    """Handlers for creating a resource pool and listing all resource pools."""

    repo: ResourcePoolRepository

    async def get(self, _: Request):
        """List all resource pools."""
        res = await self.repo.get_resource_pools()
        return json([apispec.ResourcePoolWithId.from_orm(r).dict(exclude_none=True) for r in res])

    @validate(json=apispec.ResourcePool)
    async def post(self, _: Request, body: apispec.ResourcePool):
        """Add a new resource pool."""
        rp = models.ResourcePool.from_dict(body.dict())
        res = await self.repo.insert_resource_pool(rp)
        return json(apispec.ResourcePoolWithId.from_orm(res).dict(exclude_none=True), 201)


@dataclass
class ResourcePoolView(HTTPMethodView):
    """Handlers for dealing with individual resource pools."""

    repo: ResourcePoolRepository

    async def get(self, request: Request, resource_pool_id: int):
        """Get a specific resource pool."""
        res = await self.repo.get_resource_pools(resource_pool_id, name=request.args.get("name"))
        if len(res) < 1:
            raise errors.MissingResourceError(message=f"The resource pool with id {resource_pool_id} cannot be found.")
        return json(apispec.ResourcePoolWithId.from_orm(res[0]).dict(exclude_none=True))

    async def delete(self, _: Request, resource_pool_id: int):
        """Delete a specific resource pool."""
        await self.repo.delete_resource_pool(id=resource_pool_id)
        return HTTPResponse(status=204)

    @validate(json=apispec.ResourcePoolPut)
    async def put(self, _: Request, resource_pool_id: int, body: apispec.ResourcePoolPut):
        """Update all fields of a specific resource pool."""
        return await self._put_patch_resource_pool(resource_pool_id=resource_pool_id, body=body)

    @validate(json=apispec.ResourcePoolPatch)
    async def patch(self, _: Request, resource_pool_id: int, body: apispec.ResourcePoolPatch):
        """Partially update a specific resource pool."""
        return await self._put_patch_resource_pool(resource_pool_id=resource_pool_id, body=body)

    async def _put_patch_resource_pool(
        self, resource_pool_id: int, body: apispec.ResourcePoolPut | apispec.ResourcePoolPatch
    ):
        res = await self.repo.update_resource_pool(id=resource_pool_id, **body.dict(exclude_none=True))
        if res is None:
            raise errors.MissingResourceError(message=f"The resource pool with ID {resource_pool_id} cannot be found.")
        return json(apispec.ResourcePoolWithId.from_orm(res).dict(exclude_none=True))


@dataclass
class ResourcePoolUsersView(HTTPMethodView):
    """Handlers for dealing with the users of individual resource pools."""

    repo: UserRepository

    async def get(self, _: Request, resource_pool_id: int):
        """Get all users of a specific resource pool."""
        res = await self.repo.get_users(resource_pool_id=resource_pool_id)
        return json(
            [
                apispec.UserWithId(id=r.keycloak_id).dict(exclude_none=True)
                for r in res
            ]
        )

    @validate(json=apispec.UsersWithId)
    async def post(self, _: Request, resource_pool_id: int, body: apispec.UsersWithId):
        """Add users to a specific resource pool."""
        return await self._put_post(resource_pool_id=resource_pool_id, body=body, post=True)

    @validate(json=apispec.UsersWithId)
    async def put(self, _: Request, resource_pool_id: int, body: apispec.UsersWithId):
        """Set the users for a specific resource pool."""
        return await self._put_post(resource_pool_id=resource_pool_id, body=body, post=False)

    async def _put_post(self, resource_pool_id: int, body: apispec.UsersWithId, post: bool = True):
        users = [models.User(keycloak_id=user.id) for user in body.__root__]
        rp = await self.repo.update_resource_pool_users(resource_pool_id=resource_pool_id, users=users, append=post)
        return json(apispec.ResourcePoolWithId.from_orm(rp).dict(exclude_none=True))


@dataclass
class ResourcePoolUserView(HTTPMethodView):
    """Handlers for dealing with an individual user of an individual resource pool."""

    repo: UserRepository

    async def get(self, _: Request, resource_pool_id: int, user_id: str):
        """Get a specific user of a specific resource pool."""
        res = await self.repo.get_users(keycloak_id=user_id, resource_pool_id=resource_pool_id)
        if len(res) < 1:
            raise errors.MissingResourceError(
                message=f"The user with id {user_id} or resource pool with id {resource_pool_id} cannot be found."
            )
        return json(
            apispec.UserWithId(id=res[0].keycloak_id).dict(exclude_none=True)
        )

    async def delete(self, _: Request, resource_pool_id: int, user_id: str):
        """Delete a specific user of a specific resource pool."""
        await self.repo.delete_resource_pool_user(resource_pool_id=resource_pool_id, keycloak_id=user_id)
        return HTTPResponse(status=204)


@dataclass
class ClassesView(HTTPMethodView):
    """Handlers for dealing with resource classes of an individual resource pool."""

    repo: ResourcePoolRepository

    async def get(self, request: Request, resource_pool_id: int):
        """Get the classes of a specific resource pool."""
        res = await self.repo.get_classes(resource_pool_id=resource_pool_id, name=request.args.get("name"))
        return json([apispec.ResourceClassWithId.from_orm(r).dict(exclude_none=True) for r in res])

    @validate(json=apispec.ResourceClass)
    async def post(self, _: Request, body: apispec.ResourceClass, resource_pool_id: int):
        """Add a class to a specific resource pool."""
        rps = await self.repo.get_resource_pools(id=resource_pool_id)
        if len(rps) < 1:
            raise errors.MissingResourceError(message=f"The resource pool with id {resource_pool_id} cannot be found.")
        rp = rps[0]
        cls = models.ResourceClass.from_dict(body.dict())
        res = await self.repo.insert_resource_class(cls, resource_pool_id=rp.id)
        return json(apispec.ResourceClassWithId.from_orm(res).dict(exclude_none=True), 201)


@dataclass
class ClassView(HTTPMethodView):
    """Handlers for dealing with a specific resource class of an individual resource pool."""

    repo: ResourcePoolRepository

    async def get(self, _: Request, resource_pool_id: int, class_id: int):
        """Get a specific class of a specific resource pool."""
        res = await self.repo.get_classes(resource_pool_id=resource_pool_id, id=class_id)
        if len(res) < 1:
            raise errors.MissingResourceError(
                message=f"The class with id {class_id} or resource pool with id {resource_pool_id} cannot be found."
            )
        return json(apispec.ResourceClassWithId.from_orm(res[0]).dict(exclude_none=True))

    async def delete(self, _: Request, resource_pool_id: int, class_id: int):
        """Delete a specific class from a specific resource pool."""
        await self.repo.delete_resource_class(resource_pool_id=resource_pool_id, resource_class_id=class_id)
        return HTTPResponse(status=204)

    @validate(json=apispec.ResourceClass)
    async def put(self, _: Request, body: apispec.ResourceClass, resource_pool_id: int, class_id: int):
        """Update all fields of a specific resource class for a specific resource pool."""
        return await self._put_patch(resource_pool_id, class_id, body)

    @validate(json=apispec.ResourceClassPatch)
    async def patch(self, _: Request, body: apispec.ResourceClassPatch, resource_pool_id: int, class_id: int):
        """Partially update a specific resource class for a specific resource pool."""
        return await self._put_patch(resource_pool_id, class_id, body)

    async def _put_patch(
        self, resource_pool_id: int, class_id: int, body: apispec.ResourceClassPatch | apispec.ResourceClass
    ):
        cls = await self.repo.update_resource_class(
            resource_pool_id=resource_pool_id, resource_class_id=class_id, **body.dict(exclude_none=True)
        )
        return json(apispec.ResourceClassWithId.from_orm(cls).dict(exclude_none=True))


@dataclass
class QuotaView(HTTPMethodView):
    """Handlers for dealing with a quota."""

    repo: ResourcePoolRepository

    async def get(self, _: Request, resource_pool_id: int):
        """Get the quota for a specific resource pool."""
        res = await self.repo.get_quota(resource_pool_id=resource_pool_id)
        if res is None:
            raise errors.MissingResourceError(
                message=f"The quota for the resource pool with ID {resource_pool_id} cannot be found."
            )
        return json(apispec.Resources.from_orm(res).dict(exclude_none=True))

    @validate(json=apispec.Resources)
    async def put(self, _: Request, resource_pool_id: int, body: apispec.Resources):
        """Update all fields of a the quota of a specific resource pool."""
        return await self._put_patch(resource_pool_id, body)

    @validate(json=apispec.ResourcesPatch)
    async def patch(self, _: Request, resource_pool_id: int, body: apispec.ResourcesPatch):
        """Partially update the quota of a specific resource pool."""
        return await self._put_patch(resource_pool_id, body)

    async def _put_patch(self, resource_pool_id: int, body: apispec.ResourcesPatch | apispec.Resources):
        res = await self.repo.update_quota(resource_pool_id=resource_pool_id, **body.dict(exclude_none=True))
        if res is None:
            raise errors.MissingResourceError(
                message=f"The quota or the resource pool with ID {resource_pool_id} cannot be found."
            )
        return json(apispec.Resources.from_orm(res).dict(exclude_none=True))


@dataclass
class UsersView(HTTPMethodView):
    """Handlers for creating and listing users."""

    repo: UserRepository
    user_store: models.UserStore

    @validate(json=apispec.UserWithId)
    async def post(self, _: Request, body: apispec.UserWithId):
        """Add a new user. The user has to exist in Keycloak."""
        users_db, user_kc = await asyncio.gather(
            self.repo.get_users(keycloak_id=body.id),
            self.user_store.get_user_by_id(body.id),
        )
        user_db = users_db[0] if len(users_db) >= 1 else None
        # The user does not exist in keycloak, delete it form the crac database and fail.
        if user_kc is None:
            await self.repo.delete_user(body.id)
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
        user = await self.repo.insert_user(models.User(keycloak_id=body.id))
        return json(
            apispec.UserWithId(id=user.keycloak_id).dict(exclude_none=True),
            201,
        )

    async def get(self, _: Request):
        """Get all users. Please note that this is a subset of the users from Keycloak."""
        res = await self.repo.get_users()
        return json(
            [
                apispec.UserWithId(id=r.keycloak_id).dict(exclude_none=True)
                for r in res
            ]
        )


@dataclass
class UserView(HTTPMethodView):
    """Handler for dealing with a specific user."""

    repo: UserRepository

    async def delete(self, _: Request, user_id: str):
        """Delete a specific user, removing them from any resource pool they had access to."""
        await self.repo.delete_user(user_id)
        return HTTPResponse(status=204)


@dataclass
class UserResourcePoolsView(HTTPMethodView):
    """Handlers for dealing wiht the resource pools of a specific user."""

    repo: UserRepository

    async def get(self, _: Request, user_id: str):
        """Get all resource pools that a specific user has access to."""
        rps = await self.repo.get_user_resource_pools(keycloak_id=user_id)
        return json([apispec.ResourcePoolWithId.from_orm(rp).dict(exclude_none=True) for rp in rps])

    @validate(json=apispec.IntegerIds)
    async def post(self, _: Request, user_id: str, body: apispec.IntegerIds):
        """Give a specific user access to a specific resource pool."""
        return await self._post_put(user_id=user_id, post=True, resource_pool_ids=body)

    @validate(json=apispec.IntegerIds)
    async def put(self, _: Request, user_id: str, body: apispec.IntegerIds):
        """Set the list of resource pools that a specific user has access to."""
        return await self._post_put(user_id=user_id, post=False, resource_pool_ids=body)

    async def _post_put(self, user_id: str, resource_pool_ids: apispec.IntegerIds, post: bool = True):
        rps = await self.repo.update_user_resource_pools(
            keycloak_id=user_id, resource_pool_ids=resource_pool_ids.__root__, append=post
        )
        return json([apispec.ResourcePoolWithId.from_orm(rp).dict(exclude_none=True) for rp in rps])


@dataclass
class GeneralViews:
    """Server contains all handlers for CRAC and the configuration."""

    apispec: Dict[str, Any]
    version: str

    def _get_apispec(self):
        async def handler(_: Request):
            return json(self.apispec)

        return handler

    def _get_error(self):
        async def handler(_: Request):
            raise errors.ValidationError(message="Sample validation error")

        return handler

    def _get_version(self):
        async def handler(_: Request):
            return json({"version": self.version})

        return handler

    def register_handlers(self, app: Sanic) -> Sanic:
        """Register generic handlers on the provided application."""
        _ = app.get("/api/data/spec.json", name="api_spec")(self._get_apispec())
        _ = app.get("/api/data/error", name="error")(self._get_error())
        _ = app.get("/api/data/version", name="version")(self._get_version())
        return app


def register_all_handlers(app: Sanic, config: Config) -> Sanic:
    """Register all handlers on the application."""
    app.add_route(ResourcePoolsView.as_view(config.rp_repo), "/api/data/resource_pools")
    app.add_route(ResourcePoolView.as_view(config.rp_repo), "/api/data/resource_pools/<resource_pool_id>")
    app.add_route(ResourcePoolUsersView.as_view(config.user_repo), "/api/data/resource_pools/users")
    app.add_route(ResourcePoolUserView.as_view(config.user_repo), "/api/data/resource_pools/users/<user_id>")
    app.add_route(ClassesView.as_view(config.rp_repo), "/api/data/resource_pools/classes")
    app.add_route(ClassView.as_view(config.rp_repo), "/api/data/resource_pools/classes/<class_id>")
    app.add_route(QuotaView.as_view(config.rp_repo), "/api/data/resource_pools/quota")
    app.add_route(UsersView.as_view(config.user_repo, config.user_store), "/api/data/users")
    app.add_route(UserView.as_view(config.user_repo), "/api/data/users/<user_id>")
    app.add_route(UserResourcePoolsView.as_view(config.user_repo), "/api/data/users/<user_id>/resource_pools")
    app = GeneralViews(config.spec, config.version).register_handlers(app)
    app.error_handler = CustomErrorHandler()
    app.config.OAS = False
    app.config.OAS_UI_REDOC = False
    app.config.OAS_UI_SWAGGER = False
    app.config.OAS_AUTODOC = False
    return app
