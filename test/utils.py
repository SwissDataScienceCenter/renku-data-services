import typing
from dataclasses import asdict
from typing import Any

from sanic import Request
from sanic_testing.testing import ASGI_HOST, ASGI_PORT, SanicASGITestClient, TestingResponse

import renku_data_services.base_models as base_models
from renku_data_services.crc import models as rp_models
from renku_data_services.crc.db import ResourcePoolRepository
from renku_data_services.storage import models as storage_models
from renku_data_services.storage.db import StorageRepository
from renku_data_services.users import models as user_preferences_models
from renku_data_services.users.db import UserPreferencesRepository


class SanicReusableASGITestClient(SanicASGITestClient):
    """Reuasable async test client for sanic.

    Sanic has 3 test clients, SanicTestClient (sync), SanicASGITestClient (async) and ReusableClient (sync).
    The first two will drop all routes and server state before each request (!) and calculate all routes
    again and execute server start code again (!), whereas the latter only does that once per client, but
    isn't async. This can cost as much as 40% of test execution time.
    This class is essentially a combination of SanicASGITestClient and ReuasbleClient.
    """

    set_up = False

    async def __aenter__(self):
        self.set_up = True
        await self.run()
        return self

    async def __aexit__(self, *_):
        self.set_up = False
        await self.stop()

    async def run(self):
        self.sanic_app.router.reset()
        self.sanic_app.signal_router.reset()
        await self.sanic_app._startup()  # type: ignore
        await self.sanic_app._server_event("init", "before")
        await self.sanic_app._server_event("init", "after")
        for route in self.sanic_app.router.routes:
            if self._collect_request not in route.extra.request_middleware:
                route.extra.request_middleware.appendleft(self._collect_request)
        if self._collect_request not in self.sanic_app.request_middleware:
            self.sanic_app.request_middleware.appendleft(
                self._collect_request  # type: ignore
            )

    async def stop(self):
        await self.sanic_app._server_event("shutdown", "before")
        await self.sanic_app._server_event("shutdown", "after")

    async def request(  # type: ignore
        self, method, url, gather_request=True, *args, **kwargs
    ) -> tuple[typing.Optional[Request], typing.Optional[TestingResponse]]:
        if not self.set_up:
            raise RuntimeError(
                "Trying to call request without first entering context manager. Only use this class in a `with` block"
            )

        if not url.startswith(("http:", "https:", "ftp:", "ftps://", "//", "ws:", "wss:")):
            url = url if url.startswith("/") else f"/{url}"
            scheme = "ws" if method == "websocket" else "http"
            url = f"{scheme}://{ASGI_HOST}:{ASGI_PORT}{url}"

        self.gather_request = gather_request
        # call SanicASGITestClient's parent request method
        response = await super(SanicASGITestClient, self).request(method, url, *args, **kwargs)

        response.__class__ = TestingResponse

        if gather_request:
            return self.last_request, response  # type: ignore
        return None, response  # type: ignore


def remove_id_from_quota(quota: rp_models.Quota) -> rp_models.Quota:
    kwargs = asdict(quota)
    kwargs["id"] = None
    return rp_models.Quota(**kwargs)


def remove_id_from_rc(rc: rp_models.ResourceClass) -> rp_models.ResourceClass:
    kwargs = asdict(rc)
    kwargs["id"] = None
    return rp_models.ResourceClass.from_dict(kwargs)


def remove_id_from_rp(rp: rp_models.ResourcePool) -> rp_models.ResourcePool:
    quota = rp.quota
    if isinstance(quota, rp_models.Quota):
        quota = remove_id_from_quota(quota)
    classes = [remove_id_from_rc(rc) for rc in rp.classes]
    return rp_models.ResourcePool(
        name=rp.name,
        id=None,
        quota=quota,
        classes=classes,
        default=rp.default,
        public=rp.public,
        idle_threshold=rp.idle_threshold,
        hibernation_threshold=rp.hibernation_threshold,
    )


def remove_id_from_user(user: base_models.User) -> base_models.User:
    kwargs = asdict(user)
    kwargs["id"] = None
    return base_models.User(**kwargs)


async def create_rp(
    rp: rp_models.ResourcePool, repo: ResourcePoolRepository, api_user: base_models.APIUser
) -> rp_models.ResourcePool:
    inserted_rp = await repo.insert_resource_pool(api_user, rp)
    assert inserted_rp is not None
    assert inserted_rp.id is not None
    assert inserted_rp.quota is not None
    assert all([rc.id is not None for rc in inserted_rp.classes])
    inserted_rp_no_ids = remove_id_from_rp(inserted_rp)
    assert rp == inserted_rp_no_ids, f"resource pools do not match {rp} != {inserted_rp_no_ids}"
    retrieved_rps = await repo.get_resource_pools(api_user, inserted_rp.id)
    assert len(retrieved_rps) == 1
    assert inserted_rp.id == retrieved_rps[0].id
    assert inserted_rp.name == retrieved_rps[0].name
    assert inserted_rp.idle_threshold == retrieved_rps[0].idle_threshold
    assert inserted_rp.classes == retrieved_rps[0].classes
    assert inserted_rp.quota == retrieved_rps[0].quota
    return inserted_rp


async def create_storage(storage_dict: dict[str, Any], repo: StorageRepository, user: base_models.APIUser):
    storage_dict["configuration"] = storage_models.RCloneConfig.model_validate(storage_dict["configuration"])
    storage = storage_models.CloudStorage.model_validate(storage_dict)

    inserted_storage = await repo.insert_storage(storage, user=user)
    assert inserted_storage is not None
    assert inserted_storage.storage_id is not None
    retrieved_storage = await repo.get_storage_by_id(inserted_storage.storage_id, user=user)
    assert retrieved_storage is not None

    assert inserted_storage.model_dump() == retrieved_storage.model_dump()
    return inserted_storage


async def create_user_preferences(
    project_slug: str, repo: UserPreferencesRepository, user: base_models.APIUser
) -> user_preferences_models.UserPreferences:
    """Create user preferencers by adding a pinned project"""
    user_preferences = await repo.add_pinned_project(requested_by=user, project_slug=project_slug)
    assert user_preferences is not None
    assert user_preferences.user_id is not None
    assert user_preferences.pinned_projects is not None
    assert project_slug in user_preferences.pinned_projects.project_slugs

    return user_preferences
