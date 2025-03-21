"""ActivityPub blueprint."""

import json
import logging
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

from sanic import HTTPResponse, Request
from sanic.response import JSONResponse, text
from sanic_ext import validate
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services.activitypub import apispec, core, models
from renku_data_services.base_api.auth import authenticate
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_models.validation import validate_and_dump, validated_json
from renku_data_services.errors import errors


logger = logging.getLogger(__name__)


@dataclass(kw_only=True)
class ActivityPubBP(CustomBlueprint):
    """Handlers for ActivityPub."""

    activitypub_service: core.ActivityPubService
    authenticator: base_models.Authenticator
    config: models.ActivityPubConfig

    def get_project_actor(self) -> BlueprintFactoryResponse:
        """Get the ActivityPub actor for a project."""

        @authenticate(self.authenticator)
        async def _get_project_actor(request: Request, user: base_models.APIUser, project_id: ULID) -> JSONResponse:
            try:
                actor = await self.activitypub_service.get_project_actor(user=user, project_id=project_id)
                return JSONResponse(
                    self.activitypub_service._to_dict(actor),
                    status=200,
                    headers={"Content-Type": "application/activity+json"},
                )
            except errors.MissingResourceError as e:
                return JSONResponse(
                    {"error": "not_found", "message": str(e)},
                    status=404,
                )

        return "/ap/projects/<project_id:ulid>", ["GET"], _get_project_actor

    def get_project_followers(self) -> BlueprintFactoryResponse:
        """Get the followers of a project."""

        @authenticate(self.authenticator)
        async def _get_project_followers(request: Request, user: base_models.APIUser, project_id: ULID) -> JSONResponse:
            try:
                followers = await self.activitypub_service.get_project_followers(user=user, project_id=project_id)
                return validated_json(apispec.ProjectFollowers, {"followers": followers})
            except errors.MissingResourceError as e:
                return JSONResponse(
                    {"error": "not_found", "message": str(e)},
                    status=404,
                )

        return "/ap/projects/<project_id:ulid>/followers", ["GET"], _get_project_followers

    def remove_project_follower(self) -> BlueprintFactoryResponse:
        """Remove a follower from a project."""

        @authenticate(self.authenticator)
        async def _remove_project_follower(
            request: Request, user: base_models.APIUser, project_id: ULID, follower_uri: str
        ) -> JSONResponse:
            try:
                # URL-decode the follower_uri
                follower_uri = urllib.parse.unquote(follower_uri)

                # Remove the follower
                await self.activitypub_service.handle_unfollow(user=user, project_id=project_id, follower_actor_uri=follower_uri)

                # Return a 204 No Content response
                return JSONResponse(None, status=204)
            except errors.MissingResourceError as e:
                return JSONResponse(
                    {"error": "not_found", "message": str(e)},
                    status=404,
                )

        return "/ap/projects/<project_id:ulid>/followers/<follower_uri:path>", ["DELETE"], _remove_project_follower

    def project_inbox(self) -> BlueprintFactoryResponse:
        """Receive an ActivityPub activity for a project."""

        @authenticate(self.authenticator)
        async def _project_inbox(request: Request, user: base_models.APIUser, project_id: ULID) -> HTTPResponse:
            try:
                # Parse the activity
                activity_json = request.json
                if not activity_json:
                    return JSONResponse(
                        {"error": "invalid_request", "message": "Invalid activity: empty request body"},
                        status=400,
                    )

                # Check if the activity is a Follow activity
                activity_type = activity_json.get("type")
                if activity_type == models.ActivityType.FOLLOW:
                    # Get the actor URI
                    actor_uri = activity_json.get("actor")
                    if not actor_uri:
                        return JSONResponse(
                            {"error": "invalid_request", "message": "Invalid activity: missing actor"},
                            status=400,
                        )

                    try:
                        # Handle the follow request
                        await self.activitypub_service.handle_follow(
                            user=user, project_id=project_id, follower_actor_uri=actor_uri
                        )
                        return HTTPResponse(status=200)
                    except Exception as e:
                        logger.exception(f"Error handling follow activity: {e}")
                        return JSONResponse(
                            {"error": "internal_error", "message": f"Error handling follow: {str(e)}"},
                            status=500,
                        )
                elif activity_type == models.ActivityType.UNDO:
                    # Check if the object is a Follow activity
                    object_json = activity_json.get("object", {})
                    if isinstance(object_json, dict) and object_json.get("type") == models.ActivityType.FOLLOW:
                        # Get the actor URI
                        actor_uri = activity_json.get("actor")
                        if not actor_uri:
                            return JSONResponse(
                                {"error": "invalid_request", "message": "Invalid activity: missing actor"},
                                status=400,
                            )

                        try:
                            # Handle the unfollow request
                            await self.activitypub_service.handle_unfollow(
                                user=user, project_id=project_id, follower_actor_uri=actor_uri
                            )
                            return HTTPResponse(status=200)
                        except Exception as e:
                            logger.exception(f"Error handling unfollow activity: {e}")
                            return JSONResponse(
                                {"error": "internal_error", "message": f"Error handling unfollow: {str(e)}"},
                                status=500,
                            )

                # For other activity types, just acknowledge receipt
                return HTTPResponse(status=200)
            except errors.MissingResourceError as e:
                return JSONResponse(
                    {"error": "not_found", "message": str(e)},
                    status=404,
                )
            except Exception as e:
                logger.exception(f"Error handling activity: {e}")
                return JSONResponse(
                    {"error": "internal_error", "message": f"An internal error occurred: {str(e)}"},
                    status=500,
                )

        return "/ap/projects/<project_id:ulid>/inbox", ["POST"], _project_inbox

    def get_project_outbox(self) -> BlueprintFactoryResponse:
        """Get the outbox of a project."""

        @authenticate(self.authenticator)
        async def _get_project_outbox(request: Request, user: base_models.APIUser, project_id: ULID) -> JSONResponse:
            try:
                # Get the project actor
                actor = await self.activitypub_service.get_project_actor(user=user, project_id=project_id)

                # For now, return an empty collection
                # In the future, this could be populated with activities from the project
                collection = {
                    "@context": ["https://www.w3.org/ns/activitystreams"],
                    "id": f"{actor.id}/outbox",
                    "type": "OrderedCollection",
                    "totalItems": 0,
                    "first": f"{actor.id}/outbox?page=1",
                    "last": f"{actor.id}/outbox?page=1",
                }

                return JSONResponse(
                    collection,
                    status=200,
                    headers={"Content-Type": "application/activity+json"},
                )
            except errors.MissingResourceError as e:
                return JSONResponse(
                    {"error": "not_found", "message": str(e)},
                    status=404,
                )

        return "/ap/projects/<project_id:ulid>/outbox", ["GET"], _get_project_outbox

    def webfinger(self) -> BlueprintFactoryResponse:
        """WebFinger endpoint."""

        async def _webfinger(request: Request) -> JSONResponse:
            resource = request.args.get("resource")
            if not resource:
                return JSONResponse(
                    {"error": "invalid_request", "message": "Missing resource parameter"},
                    status=400,
                )

            # Parse the resource
            # Format: acct:username@domain or https://domain/ap/projects/project_id
            if resource.startswith("acct:"):
                # acct:username@domain
                parts = resource[5:].split("@")
                if len(parts) != 2 or parts[1] != self.config.domain:
                    return JSONResponse(
                        {"error": "not_found", "message": f"Resource {resource} not found"},
                        status=404,
                    )

                username = parts[0]
                try:
                    # Get the actor by username
                    actor = await self.activitypub_service.get_project_actor_by_username(username=username)

                    # Create the WebFinger response
                    response = {
                        "subject": resource,
                        "aliases": [actor.id],
                        "links": [
                            {
                                "rel": "self",
                                "type": "application/activity+json",
                                "href": actor.id,
                            }
                        ],
                    }

                    return JSONResponse(
                        response,
                        status=200,
                        headers={"Content-Type": "application/jrd+json"},
                    )
                except errors.MissingResourceError:
                    return JSONResponse(
                        {"error": "not_found", "message": f"Resource {resource} not found"},
                        status=404,
                    )
            elif resource.startswith("https://") or resource.startswith("http://"):
                # https://domain/ap/projects/project_id
                parsed_url = urlparse(resource)
                path_parts = parsed_url.path.strip("/").split("/")

                if len(path_parts) >= 3 and path_parts[0] == "ap" and path_parts[1] == "projects":
                    try:
                        project_id = ULID.from_str(path_parts[2])

                        # Get the actor
                        # Create a user with no authentication
                        # The project_repo.get_project method will check if the project is public
                        user = base_models.APIUser(id=None, is_admin=False)
                        actor = await self.activitypub_service.get_project_actor(user=user, project_id=project_id)

                        # Create the WebFinger response
                        response = {
                            "subject": resource,
                            "aliases": [f"acct:{actor.preferredUsername}@{self.config.domain}"],
                            "links": [
                                {
                                    "rel": "self",
                                    "type": "application/activity+json",
                                    "href": actor.id,
                                }
                            ],
                        }

                        return JSONResponse(
                            response,
                            status=200,
                            headers={"Content-Type": "application/jrd+json"},
                        )
                    except (errors.MissingResourceError, ValueError):
                        return JSONResponse(
                            {"error": "not_found", "message": f"Resource {resource} not found"},
                            status=404,
                        )

            return JSONResponse(
                {"error": "not_found", "message": f"Resource {resource} not found"},
                status=404,
            )

        return "/ap/webfinger", ["GET"], _webfinger

    def host_meta(self) -> BlueprintFactoryResponse:
        """Host metadata endpoint."""

        async def _host_meta_handler(request: Request) -> HTTPResponse:
            # Create the XML response
            template = self.config.base_url + "/ap/webfinger?resource={uri}"
            xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
            xml_content += '<XRD xmlns="http://docs.oasis-open.org/ns/xri/xrd-1.0">\n'
            xml_content += f'  <Link rel="lrdd" template="{template}"/>\n'
            xml_content += '</XRD>'

            # Return the response
            return text(
                xml_content,
                status=200,
                headers={"Content-Type": "application/xrd+xml"},
            )

        return "/ap/.well-known/host-meta", ["GET"], _host_meta_handler

    def nodeinfo(self) -> BlueprintFactoryResponse:
        """NodeInfo endpoint."""

        async def _nodeinfo(request: Request) -> JSONResponse:
            response = {
                "links": [
                    {
                        "rel": "http://nodeinfo.diaspora.software/ns/schema/2.0",
                        "href": f"{self.config.base_url}/ap/nodeinfo/2.0",
                    }
                ]
            }

            return JSONResponse(
                response,
                status=200,
                headers={"Content-Type": "application/json"},
            )

        return "/ap/.well-known/nodeinfo", ["GET"], _nodeinfo

    def nodeinfo_2_0(self) -> BlueprintFactoryResponse:
        """NodeInfo 2.0 endpoint."""

        async def _nodeinfo_2_0(request: Request) -> JSONResponse:
            response = {
                "version": "2.0",
                "software": {
                    "name": "renku",
                    "version": "1.0.0",
                },
                "protocols": ["activitypub"],
                "services": {
                    "inbound": [],
                    "outbound": [],
                },
                "usage": {
                    "users": {
                        "total": 1,  # Placeholder
                    },
                    "localPosts": 0,  # Placeholder
                },
                "openRegistrations": False,
                "metadata": {
                    "nodeName": "Renku",
                    "nodeDescription": "Renku ActivityPub Server",
                },
            }

            return JSONResponse(
                response,
                status=200,
                headers={"Content-Type": "application/json; profile=http://nodeinfo.diaspora.software/ns/schema/2.0#"},
            )

        return "/ap/nodeinfo/2.0", ["GET"], _nodeinfo_2_0
