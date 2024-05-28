"""Custom blueprint wrapper for Sanic."""

from collections.abc import Callable
from dataclasses import dataclass, field
from inspect import getmembers, ismethod
from typing import Optional, cast

from sanic import Blueprint
from sanic.models.handler_types import RequestMiddlewareType, ResponseMiddlewareType, RouteHandler


@dataclass(kw_only=True)
class CustomBlueprint:
    """A wrapper around Sanic blueprint.

    It will take all "public" methods (i.e. whose names do not start with "_")
    and register them to a Sanic blueprint. The idea is that any real blueprint inherits this and defines
    additional public methods all of which return Sanic route handlers. See the BlueprintFactory type for the
    signature that the methods are supposed to have. The return value should return a tuple of the url for the route
    (i.e. "/api"), the list of methods (i.e. GET, POST, PATCH) and the handler itself.
    """

    name: str
    url_prefix: Optional[str] = None
    request_middlewares: list[RequestMiddlewareType] = field(default_factory=list, repr=False)
    response_middlewares: list[ResponseMiddlewareType] = field(default_factory=list, repr=False)

    def blueprint(self) -> Blueprint:
        """Generates the Sanic blueprint from all public methods."""
        bp = Blueprint(name=self.name, url_prefix=self.url_prefix)
        members = getmembers(self, ismethod)
        for name, method in members:
            if name != "blueprint" and not name.startswith("_"):
                method_factory = cast(BlueprintFactory, method)
                url, http_methods, handler = method_factory()
                bp.add_route(handler=handler, uri=url, methods=http_methods, name=name)
        for req_mw in self.request_middlewares:
            bp.middleware("request")(req_mw)
        for res_mw in self.response_middlewares:
            bp.middleware("response")(res_mw)
        return bp


BlueprintFactoryResponse = tuple[str, list[str], RouteHandler]
BlueprintFactory = Callable[..., BlueprintFactoryResponse]
