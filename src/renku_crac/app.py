"""Compute resource access control (CRAC) app."""
from dataclasses import dataclass
from typing import Type, cast

from pydantic import EmailStr
from sanic import HTTPResponse, Request, Sanic, json
from sanic_ext import validate

from src import models
from src.models import errors
from src.renku_crac.config import Config
from src.renku_crac.error_handler import CustomErrorHandler
from src.schemas import apispec


@dataclass
class Server:
    """Server contains all handlers for CRAC and the configuration."""

    config: Config

    def _get_resource_pool(self):
        async def handler(request: Request, resource_pool_id: int):
            res = await self.config.db.get_resource_pools(resource_pool_id, name=request.args.get("name"))
            if len(res) < 1:
                raise errors.MissingResourceError(
                    message=f"The resource pool with id {resource_pool_id} cannot be found."
                )
            return json(apispec.ResourcePoolWithId.from_orm(res[0]).dict(exclude_none=True))

        return handler

    def _get_resource_pools(self):
        async def handler(_: Request):
            res = await self.config.db.get_resource_pools()
            return json([apispec.ResourcePoolWithId.from_orm(r).dict(exclude_none=True) for r in res])

        return handler

    def _post_resource_pools(self):
        @validate(json=apispec.ResourcePool)
        async def handler(_: Request, body: apispec.ResourcePool):
            rp = models.ResourcePool.from_dict(body.dict())
            res = await self.config.db.insert_resource_pool(rp)
            return json(apispec.ResourcePoolWithId.from_orm(res).dict(exclude_none=True), 201)

        return handler

    def _post_user(self):
        @validate(json=apispec.UserWithId)
        async def handler(_: Request, body: apispec.UserWithId):
            users = await self.config.db.get_users(keycloak_id=body.id)
            if len(users) == 1:
                # The user already exists in the crac db
                user = users[0]
                if user.username != body.username:
                    # The username in keycloak is different, so update the user to have the username from keycloak
                    user = await self.config.db.update_user(keycloak_id=cast(int, user.id), username=body.username)
                return json(
                    apispec.UserWithId(id=user.keycloak_id, username=cast(EmailStr, user.username)).dict(
                        exclude_none=True
                    ),
                    200,
                )
            user_kc = await self.config.user_store.get_user_by_id(cast(str, body.id))
            if user_kc is None:
                raise errors.MissingResourceError(message=f"User with id {body.id} cannot be found in keycloak.")
            if user_kc.username != body.username:
                raise errors.ValidationError(
                    message=f"The provided username {body.username} does not "
                    f"match the keycloak useranme {user_kc.username}."
                )
            # The user exists in keycloak, so we can add it in our database
            user = await self.config.db.insert_user(user_kc)
            return json(
                apispec.UserWithId(id=user.keycloak_id, username=cast(EmailStr, user.username)).dict(exclude_none=True),
                201,
            )

        return handler

    def _get_users(self):
        async def handler(request: Request):
            res = await self.config.db.get_users(username=request.args.get("username"))
            return json(
                [
                    apispec.UserWithId(id=r.keycloak_id, username=cast(EmailStr, r.username)).dict(exclude_none=True)
                    for r in res
                ]
            )

        return handler

    def _delete_user(self):
        async def handler(_: Request, id: str):
            await self.config.db.delete_user(id)
            return HTTPResponse(status=204)

        return handler

    def _get_resource_pool_users(self):
        async def handler(request: Request, resource_pool_id: int):
            res = await self.config.db.get_users(
                resource_pool_id=resource_pool_id, username=request.args.get("username")
            )
            return json(
                [
                    apispec.UserWithId(id=r.keycloak_id, username=cast(EmailStr, r.username)).dict(exclude_none=True)
                    for r in res
                ]
            )

        return handler

    def _get_resource_pool_user(self):
        async def handler(_: Request, resource_pool_id: int, user_id: str):
            res = await self.config.db.get_users(keycloak_id=user_id, resource_pool_id=resource_pool_id)
            if len(res) < 1:
                raise errors.MissingResourceError(
                    message=f"The user with id {user_id} or resource pool with id {resource_pool_id} cannot be found."
                )
            return json(
                apispec.UserWithId(id=res[0].keycloak_id, username=cast(EmailStr, res[0].username)).dict(
                    exclude_none=True
                )
            )

        return handler

    def _get_resource_pool_classes(self):
        async def handler(request: Request, resource_pool_id: int):
            res = await self.config.db.get_classes(resource_pool_id=resource_pool_id, name=request.args.get("name"))
            return json([apispec.ResourceClassWithId.from_orm(r).dict(exclude_none=True) for r in res])

        return handler

    def _get_resource_pool_class(self):
        async def handler(_: Request, resource_pool_id: int, class_id: int):
            res = await self.config.db.get_classes(resource_pool_id=resource_pool_id, id=class_id)
            if len(res) < 1:
                raise errors.MissingResourceError(
                    message=f"The class with id {class_id} or resource pool with id {resource_pool_id} cannot be found."
                )
            return json(apispec.ResourceClassWithId.from_orm(res[0]).dict(exclude_none=True))

        return handler

    def _delete_resource_pool_class(self):
        async def handler(_: Request, resource_pool_id: int, class_id: int):
            await self.config.db.delete_resource_class(resource_pool_id=resource_pool_id, resource_class_id=class_id)
            return HTTPResponse(status=204)

        return handler

    def _put_patch_resource_pool_class(self, validation: Type[apispec.ResourceClassPatch | apispec.ResourceClass]):
        @validate(json=validation)
        async def handler(
            _: Request, resource_pool_id: int, class_id: int, body: apispec.ResourceClassPatch | apispec.ResourceClass
        ):
            cls = await self.config.db.update_resource_class(
                resource_pool_id=resource_pool_id, resource_class_id=class_id, **body.dict(exclude_none=True)
            )
            return json(apispec.ResourceClassWithId.from_orm(cls).dict(exclude_none=True))

        return handler

    def _post_resource_pool_class(self):
        @validate(json=apispec.ResourceClass)
        async def handler(_: Request, body: apispec.ResourceClass, resource_pool_id: int):
            rps = await self.config.db.get_resource_pools(id=resource_pool_id)
            if len(rps) < 1:
                raise errors.MissingResourceError(
                    message=f"The resource pool with id {resource_pool_id} cannot be found."
                )
            rp = rps[0]
            cls = models.ResourceClass.from_dict(body.dict())
            res = await self.config.db.insert_resource_class(cls, resource_pool_id=rp.id)
            return json(apispec.ResourceClassWithId.from_orm(res).dict(exclude_none=True), 201)

        return handler

    def _get_quota(self):
        async def handler(_: Request, resource_pool_id: int):
            res = await self.config.db.get_quota(resource_pool_id=resource_pool_id)
            if res is None:
                raise errors.MissingResourceError(
                    message=f"The quota for the resource pool with ID {resource_pool_id} cannot be found."
                )
            return json(apispec.Resources.from_orm(res).dict(exclude_none=True))

        return handler

    def _put_patch_quota(self, validation=Type[apispec.ResourcesPatch | apispec.Resources]):
        @validate(validation)
        async def handler(_: Request, resource_pool_id: int, body: apispec.ResourcesPatch | apispec.Resources):
            res = await self.config.db.update_quota(resource_pool_id=resource_pool_id, **body.dict(exclude_none=True))
            if res is None:
                raise errors.MissingResourceError(
                    message=f"The quota or the resource pool with ID {resource_pool_id} cannot be found."
                )
            return json(apispec.Resources.from_orm(res).dict(exclude_none=True))

        return handler

    def _put_patch_classes(self, validation=Type[apispec.ResourceClassWithId | apispec.ResourceClassPatch]):
        @validate(validation)
        async def handler(_: Request, resource_pool_id: int, body: apispec.ResourcesPatch | apispec.Resources):
            res = await self.config.db.update_quota(resource_pool_id=resource_pool_id, **body.dict(exclude_none=True))
            if res is None:
                raise errors.MissingResourceError(
                    message=f"The quota or the resource pool with ID {resource_pool_id} cannot be found."
                )
            return json(apispec.Resources.from_orm(res).dict(exclude_none=True))

        return handler

    def _put_patch_resource_pool(self, validation=Type[apispec.ResourcePoolPut | apispec.ResourcePoolPatch]):
        @validate(validation)
        async def handler(_: Request, resource_pool_id: int, body: apispec.ResourcePoolPut | apispec.ResourcePoolPatch):
            res = await self.config.db.update_resource_pool(id=resource_pool_id, **body.dict(exclude_none=True))
            if res is None:
                raise errors.MissingResourceError(
                    message=f"The resource pool with ID {resource_pool_id} cannot be found."
                )
            return json(apispec.ResourcePoolWithId.from_orm(res).dict(exclude_none=True))

        return handler

    def _delete_resource_pool(self):
        async def handler(_: Request, resource_pool_id: int):
            await self.config.db.delete_resource_pool(id=resource_pool_id)
            return HTTPResponse(status=204)

        return handler

    def _get_user_resource_pools(self):
        async def handler(_: Request, user_id: str):
            rps = await self.config.db.get_user_resource_pools(keycloak_id=user_id)
            return json([apispec.ResourcePoolWithId.from_orm(rp).dict(exclude_none=True) for rp in rps])

        return handler

    def _post_put_user_resource_pools(self, *, post: bool = True):
        async def handler(request: Request, user_id: str):
            ids = request.json
            _ = apispec.IntegerIds.parse_obj(ids)  # validation
            rps = await self.config.db.update_user_resource_pools(
                keycloak_id=user_id, resource_pool_ids=ids, append=post
            )
            return json([apispec.ResourcePoolWithId.from_orm(rp).dict(exclude_none=True) for rp in rps])

        return handler

    def _post_put_resource_pool_users(self, *, post: bool = True):
        async def handler(request: Request, resource_pool_id: int):
            users = request.json
            _ = apispec.UsersWithId.parse_obj(users)  # validation
            users = [models.User(keycloak_id=user["id"], username=user["username"]) for user in users]
            rp = await self.config.db.update_resource_pool_users(
                resource_pool_id=resource_pool_id, users=users, append=post
            )
            return json(apispec.ResourcePoolWithId.from_orm(rp).dict(exclude_none=True))

        return handler

    def _delete_resource_pool_user(self):
        async def handler(request: Request, resource_pool_id: int, user_id: str):
            await self.config.db.delete_resource_pool_user(resource_pool_id=resource_pool_id, keycloak_id=user_id)
            return HTTPResponse(status=204)

        return handler

    def _get_apispec(self):
        async def handler(_: Request):
            return json(self.config.spec)

        return handler

    def _get_error(self):
        async def handler(_: Request):
            raise errors.ValidationError(message="Sample validation error")

        return handler

    def _get_version(self):
        async def handler(_: Request):
            return json({"version": self.config.version})

        return handler

    def register_handlers(self, app: Sanic) -> Sanic:
        """Register all handlers on the provided application."""
        _ = app.get("/api/data/resource_pools", name="get_resource_pools")(self._get_resource_pools())
        _ = app.post("/api/data/resource_pools", name="post_resource_pools")(self._post_resource_pools())
        _ = app.get("/api/data/resource_pools/<resource_pool_id>", name="get_resource_pool")(self._get_resource_pool())
        _ = app.put("/api/data/resource_pools/<resource_pool_id>", name="put_resource_pool")(
            self._put_patch_resource_pool(apispec.ResourcePoolPut)
        )
        _ = app.patch("/api/data/resource_pools/<resource_pool_id>", name="patch_resource_pool")(
            self._put_patch_resource_pool(apispec.ResourcePoolPatch)
        )
        _ = app.delete("/api/data/resource_pools/<resource_pool_id>", name="delete_resource_pool")(
            self._delete_resource_pool()
        )
        _ = app.get("/api/data/users/<user_id>/resource_pools", name="get_user_resource_pools")(
            self._get_user_resource_pools()
        )
        _ = app.post("/api/data/users/<user_id>/resource_pools", name="post_user_resource_pools")(
            self._post_put_user_resource_pools(post=True)
        )
        _ = app.put("/api/data/users/<user_id>/resource_pools", name="put_user_resource_pools")(
            self._post_put_user_resource_pools(post=False)
        )
        # Users
        _ = app.post("/api/data/users", name="post_user")(self._post_user())
        _ = app.get("/api/data/users", name="get_users")(self._get_users())
        _ = app.delete("/api/data/users/<id>", name="delete_user")(self._delete_user())
        _ = app.get("/api/data/resource_pools/<resource_pool_id>/users", name="get_resource_pool_users")(
            self._get_resource_pool_users()
        )
        _ = app.post("/api/data/resource_pools/<resource_pool_id>/users", name="post_resource_pool_users")(
            self._post_put_resource_pool_users(post=True)
        )
        _ = app.put("/api/data/resource_pools/<resource_pool_id>/users", name="put_resource_pool_users")(
            self._post_put_resource_pool_users(post=False)
        )
        _ = app.get("/api/data/resource_pools/<resource_pool_id>/users/<user_id>", name="get_resource_pool_user")(
            self._get_resource_pool_user()
        )
        _ = app.delete("/api/data/resource_pools/<resource_pool_id>/users/<user_id>", name="delete_resource_pool_user")(
            self._delete_resource_pool_user()
        )
        # Classes
        _ = app.get("/api/data/resource_pools/<resource_pool_id>/classes", name="get_resource_pool_classes")(
            self._get_resource_pool_classes()
        )
        _ = app.post("/api/data/resource_pools/<resource_pool_id>/classes", name="post_resource_pool_class")(
            self._post_resource_pool_class()
        )
        _ = app.get("/api/data/resource_pools/<resource_pool_id>/classes/<class_id>", name="get_resource_pool_class")(
            self._get_resource_pool_class()
        )
        _ = app.put("/api/data/resource_pools/<resource_pool_id>/classes/<class_id>", name="put_resource_pool_class")(
            self._put_patch_resource_pool_class(apispec.ResourceClass)
        )
        _ = app.patch(
            "/api/data/resource_pools/<resource_pool_id>/classes/<class_id>", name="patch_resource_pool_class"
        )(self._put_patch_resource_pool_class(apispec.ResourceClassPatch))
        _ = app.delete(
            "/api/data/resource_pools/<resource_pool_id>/classes/<class_id>", name="delete_resource_pool_class"
        )(self._delete_resource_pool_class())
        # Quota
        _ = app.get("/api/data/resource_pools/<resource_pool_id>/quota", name="get_quota")(self._get_quota())
        _ = app.patch("/api/data/resource_pools/<resource_pool_id>/quota", name="patch_quota")(
            self._put_patch_quota(apispec.ResourcesPatch)
        )
        _ = app.put("/api/data/resource_pools/<resource_pool_id>/quota", name="put_quota")(
            self._put_patch_quota(apispec.Resources)
        )
        # Misc
        _ = app.get("/api/data/spec.json", name="api_spec")(self._get_apispec())
        _ = app.get("/api/data/error", name="error")(self._get_error())
        _ = app.get("/api/data/version", name="version")(self._get_version())
        app.error_handler = CustomErrorHandler()
        app.config.OAS = False
        app.config.OAS_UI_REDOC = False
        app.config.OAS_UI_SWAGGER = False
        app.config.OAS_AUTODOC = False
        return app
