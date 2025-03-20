"""Business logic for ActivityPub."""

import json
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional, Union
import urllib.parse
import dataclasses

import httpx
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives import hashes, serialization
import base64
from sanic.log import logger

from ulid import ULID

from renku_data_services import errors
from renku_data_services.activitypub import models
from renku_data_services.activitypub.db import ActivityPubRepository
from renku_data_services.base_models.core import APIUser
from renku_data_services.project.db import ProjectRepository
from renku_data_services.project.models import Project



class ActivityPubService:
    """Service for ActivityPub."""

    def __init__(
        self,
        activitypub_repo: ActivityPubRepository,
        project_repo: ProjectRepository,
        config: models.ActivityPubConfig,
    ) -> None:
        self.activitypub_repo = activitypub_repo
        self.project_repo = project_repo
        self.config = config

    async def get_project_actor(self, user: APIUser, project_id: ULID) -> models.ProjectActor:
        """Get the ActivityPub actor for a project."""
        # Get the project
        project = await self.project_repo.get_project(user=user, project_id=project_id)

        # Get or create the actor
        try:
            # First try to get the existing actor
            actor = await self.activitypub_repo.get_project_actor(project_id=project_id)
        except errors.MissingResourceError:
            # If it doesn't exist, create it
            actor = await self.activitypub_repo.create_project_actor(user=user, project_id=project_id)

        if not actor or not actor.id:
            raise errors.ProgrammingError(message="Failed to get or create actor for project")

        # Convert to ProjectActor
        return self._create_project_actor(project, actor)

    async def get_project_actor_by_username(self, username: str) -> models.ProjectActor:
        """Get the ActivityPub actor for a project by username."""
        # Get the actor
        actor = await self.activitypub_repo.get_actor_by_username(username)

        if actor.project_id is None:
            raise errors.MissingResourceError(message=f"Actor with username '{username}' is not a project actor.")

        # Get the project
        # Note: We're using an admin user here because we need to access the project regardless of permissions
        admin_user = APIUser(id=None, is_admin=True)
        project = await self.project_repo.get_project(user=admin_user, project_id=actor.project_id)

        # Convert to ProjectActor
        return self._create_project_actor(project, actor)

    def _create_project_actor(self, project: Project, actor: models.ActivityPubActor) -> models.ProjectActor:
        """Create a ProjectActor from a Project and ActivityPubActor."""
        project_id = f"{self.config.base_url}/ap/projects/{project.id}"

        # Set the audience based on visibility
        to = ["https://www.w3.org/ns/activitystreams#Public"] if project.visibility.value == "public" else []

        # Set the attributedTo to the user who created the project
        attributed_to = f"{self.config.base_url}/ap/users/{project.created_by}"

        # Create public key info
        public_key = {
            "id": f"{project_id}#main-key",
            "owner": project_id,
            "publicKeyPem": actor.public_key_pem,
        } if actor.public_key_pem else None

        # Generate avatar image URL
        # We use the project ID to generate a deterministic avatar
        # This uses the Gravatar Identicon service to generate a unique avatar based on the project ID
        avatar_url = f"https://www.gravatar.com/avatar/{str(project.id)}?d=identicon&s=256"

        # Create icon object for the avatar
        icon = {
            "type": "Image",
            "mediaType": "image/png",
            "url": avatar_url
        }

        return models.ProjectActor(
            id=project_id,
            name=project.name,
            preferredUsername=actor.username,
            summary=project.description,
            content=project.description,
            documentation=project.documentation,
            attributedTo=attributed_to,
            to=to,
            url=f"{self.config.base_url}/projects/{project.namespace.slug}/{project.slug}",
            published=project.creation_date,
            updated=project.updated_at,
            inbox=f"{project_id}/inbox",
            outbox=f"{project_id}/outbox",
            followers=f"{project_id}/followers",
            following=f"{project_id}/following",
            publicKey=public_key,
            keywords=project.keywords,
            repositories=project.repositories,
            visibility=project.visibility.value,
            created_by=project.created_by,
            creation_date=project.creation_date,
            updated_at=project.updated_at,
            type=models.ActorType.PROJECT,
            icon=icon,
        )

    async def get_project_followers(self, user: APIUser, project_id: ULID) -> List[str]:
        """Get the followers of a project."""
        # Get the actor
        try:
            # First try to get the existing actor
            actor = await self.activitypub_repo.get_project_actor(project_id=project_id)
        except errors.MissingResourceError:
            # If it doesn't exist, create it
            actor = await self.activitypub_repo.create_project_actor(user=user, project_id=project_id)

        if not actor or not actor.id:
            raise errors.ProgrammingError(message="Failed to get or create actor for project")

        # Get the followers
        followers = await self.activitypub_repo.get_followers(actor_id=actor.id)

        # Return only accepted followers
        return [follower.follower_actor_uri for follower in followers if follower.accepted]

    async def handle_follow(self, user: APIUser, project_id: ULID, follower_actor_uri: str) -> models.Activity:
        """Handle a follow request for a project."""
        # Get the actor
        try:
            # First try to get the existing actor
            actor = await self.activitypub_repo.get_project_actor(project_id=project_id)
            logger.debug(f"Found existing actor for project {project_id}: {actor.id}")
        except errors.MissingResourceError:
            # If it doesn't exist, create it
            logger.debug(f"Creating new actor for project {project_id}")
            actor = await self.activitypub_repo.create_project_actor(user=user, project_id=project_id)
            logger.debug(f"Created new actor for project {project_id}: {actor.id}")

        if not actor:
            raise errors.ProgrammingError(message="Failed to get or create actor for project")

        if not actor.id:
            raise errors.ProgrammingError(message=f"Actor for project {project_id} has no ID")

        # This is logged at INFO level in db.py, so use DEBUG here
        logger.debug(f"Adding follower {follower_actor_uri} to actor {actor.id}")

        # Add the follower
        follower = models.UnsavedActivityPubFollower(
            actor_id=actor.id,
            follower_actor_uri=follower_actor_uri,
            accepted=True,  # Auto-accept follows
        )

        await self.activitypub_repo.add_follower(follower)

        # Create an Accept activity
        project_actor_uri = f"{self.config.base_url}/ap/projects/{project_id}"
        activity_id = f"{project_actor_uri}/activities/{ULID()}"

        follow_activity = {
            "type": models.ActivityType.FOLLOW,
            "actor": follower_actor_uri,
            "object": project_actor_uri,
        }

        accept_activity = models.Activity(
            id=activity_id,
            type=models.ActivityType.ACCEPT,
            actor=project_actor_uri,
            object=follow_activity,
            to=[follower_actor_uri],
            published=datetime.now(UTC),
        )

        # Discover the inbox URL using WebFinger
        inbox_url = await self._discover_inbox_url(follower_actor_uri)
        if not inbox_url:
            logger.error(f"Failed to discover inbox URL for {follower_actor_uri}")
            raise errors.ProgrammingError(message=f"Failed to discover inbox URL for {follower_actor_uri}")

        logger.info(f"Delivering activity to inbox URL: {inbox_url}")
        await self._deliver_activity(actor, accept_activity, inbox_url)

        return accept_activity

    async def handle_unfollow(self, user: APIUser, project_id: ULID, follower_actor_uri: str) -> None:
        """Handle an unfollow request for a project."""
        # Get the actor
        try:
            # First try to get the existing actor
            actor = await self.activitypub_repo.get_project_actor(project_id=project_id)
        except errors.MissingResourceError:
            # If it doesn't exist, create it
            actor = await self.activitypub_repo.create_project_actor(user=user, project_id=project_id)

        if not actor or not actor.id:
            raise errors.ProgrammingError(message="Failed to get or create actor for project")

        # Remove the follower
        await self.activitypub_repo.remove_follower(actor_id=actor.id, follower_actor_uri=follower_actor_uri)

    async def announce_project_update(self, user: APIUser, project_id: ULID) -> None:
        """Announce a project update to followers."""
        # Get the actor
        try:
            # First try to get the existing actor
            actor = await self.activitypub_repo.get_project_actor(project_id=project_id)
        except errors.MissingResourceError:
            # If it doesn't exist, create it
            actor = await self.activitypub_repo.create_project_actor(user=user, project_id=project_id)

        if not actor or not actor.id:
            raise errors.ProgrammingError(message="Failed to get or create actor for project")

        # Update the actor with the latest project info
        actor = await self.activitypub_repo.update_project_actor(user=user, project_id=project_id)

        # Get the project
        project = await self.project_repo.get_project(user=user, project_id=project_id)

        # Get the followers
        followers = await self.activitypub_repo.get_followers(actor_id=actor.id)
        accepted_followers = [follower.follower_actor_uri for follower in followers if follower.accepted]

        if not accepted_followers:
            return  # No followers to announce to

        # Create an Update activity
        project_actor_uri = f"{self.config.base_url}/ap/projects/{project_id}"
        activity_id = f"{project_actor_uri}/activities/{ULID()}"

        project_actor = self._create_project_actor(project, actor)

        update_activity = models.Activity(
            id=activity_id,
            type=models.ActivityType.UPDATE,
            actor=project_actor_uri,
            object=project_actor,
            to=accepted_followers,
            published=datetime.now(UTC),
        )

        # Send the Update activity to each follower's inbox
        for follower_uri in accepted_followers:
            try:
                # Discover the inbox URL using WebFinger
                inbox_url = await self._discover_inbox_url(follower_uri)
                if not inbox_url:
                    logger.error(f"Failed to discover inbox URL for {follower_uri}")
                    continue

                logger.info(f"Delivering update activity to inbox URL: {inbox_url}")
                await self._deliver_activity(actor, update_activity, inbox_url)
            except Exception as e:
                logger.error(f"Failed to deliver update activity to {follower_uri}: {e}")

    async def _deliver_activity(
        self, actor: models.ActivityPubActor, activity: models.Activity, inbox_url: str
    ) -> None:
        """Deliver an activity to an inbox."""
        if not actor.private_key_pem:
            raise errors.ProgrammingError(message="Actor does not have a private key")

        # Convert activity to dict
        activity_dict = self._to_dict(activity)

        # Convert the activity dict to JSON
        activity_json = json.dumps(activity_dict)

        # Calculate the digest
        digest = hashes.Hash(hashes.SHA256())
        digest.update(activity_json.encode("utf-8"))
        digest_value = digest.finalize()
        digest_header = f"SHA-256={base64.b64encode(digest_value).decode('utf-8')}"

        # Parse the target URL
        parsed_url = urllib.parse.urlparse(inbox_url)
        host = parsed_url.netloc
        path = parsed_url.path

        # Create the signature string
        date = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")
        signature_string = f"(request-target): post {path}\nhost: {host}\ndate: {date}\ndigest: {digest_header}"

        # Parse the private key
        private_key = serialization.load_pem_private_key(
            actor.private_key_pem.encode("utf-8"),
            password=None,
        )

        if not isinstance(private_key, RSAPrivateKey):
            raise errors.ProgrammingError(message="Actor's private key is not an RSA key")

        # Sign the signature string
        signature = private_key.sign(
            signature_string.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        signature_b64 = base64.b64encode(signature).decode("utf-8")

        # Prepare the signature header
        actor_id = f"{self.config.base_url}/ap/projects/{actor.project_id}" if actor.project_id else f"{self.config.base_url}/ap/users/{actor.user_id}"
        key_id = f"{actor_id}#main-key"
        signature_header = f'keyId="{key_id}",algorithm="rsa-sha256",headers="(request-target) host date digest",signature="{signature_b64}"'

        # Prepare the headers
        headers = {
            "Host": host,
            "Date": date,
            "Digest": digest_header,
            "Signature": signature_header,
            "Content-Type": "application/activity+json",
            "Accept": "application/activity+json",
        }

        # Log the request details for debugging
        logger.info(f"Sending activity to {inbox_url}")
        logger.debug(f"Headers: {headers}")
        logger.debug(f"Body: {activity_json}")

        # Send the request
        async with httpx.AsyncClient() as client:
            response = await client.post(
                inbox_url,
                content=activity_json.encode("utf-8"),  # Use content instead of json to ensure exact JSON string
                headers=headers,
            )

            if response.status_code >= 400:
                logger.error(f"Failed to deliver activity to {inbox_url}: {response.status_code} {response.text}")
                raise errors.ProgrammingError(
                    message=f"Failed to deliver activity to {inbox_url}: {response.status_code}"
                )

    async def _build_signature_headers(
        self, actor: models.ActivityPubActor, target_url: str, data: Dict[str, Any]
    ) -> Dict[str, str]:
        """Build HTTP Signature headers for an ActivityPub request."""
        if not actor.private_key_pem:
            raise errors.ProgrammingError(message="Actor does not have a private key")

        # Parse the private key
        private_key = serialization.load_pem_private_key(
            actor.private_key_pem.encode("utf-8"),
            password=None,
        )

        if not isinstance(private_key, RSAPrivateKey):
            raise errors.ProgrammingError(message="Actor's private key is not an RSA key")

        # Prepare the signature
        actor_id = f"{self.config.base_url}/ap/projects/{actor.project_id}" if actor.project_id else f"{self.config.base_url}/ap/users/{actor.user_id}"
        key_id = f"{actor_id}#main-key"

        # Get the digest of the data
        data_json = json.dumps(data)
        digest = hashes.Hash(hashes.SHA256())
        digest.update(data_json.encode("utf-8"))
        digest_value = digest.finalize()
        digest_header = f"SHA-256={base64.b64encode(digest_value).decode('utf-8')}"

        # Parse the target URL
        parsed_url = urllib.parse.urlparse(target_url)
        host = parsed_url.netloc
        path = parsed_url.path

        # Create the signature string
        date = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")
        signature_string = f"(request-target): post {path}\nhost: {host}\ndate: {date}\ndigest: {digest_header}"

        # Sign the signature string
        signature = private_key.sign(
            signature_string.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        signature_b64 = base64.b64encode(signature).decode("utf-8")

        # Create the signature header
        signature_header = f'keyId="{key_id}",algorithm="rsa-sha256",headers="(request-target) host date digest",signature="{signature_b64}"'

        # Return the headers
        return {
            "Host": host,
            "Date": date,
            "Digest": digest_header,
            "Signature": signature_header,
            "Content-Type": "application/activity+json",
            "Accept": "application/activity+json",
        }

    async def _discover_inbox_url(self, actor_uri: str) -> Optional[str]:
        """Discover the inbox URL for an actor using WebFinger and ActivityPub.

        This method follows the ActivityPub discovery process:
        1. Parse the actor URI to extract the domain and username
        2. Perform a WebFinger lookup to get the actor's profile URL
        3. Fetch the actor's profile to get the inbox URL
        """
        logger.info(f"Discovering inbox URL for actor: {actor_uri}")

        try:
            # Parse the actor URI
            parsed_uri = urllib.parse.urlparse(actor_uri)
            domain = parsed_uri.netloc

            # Handle different URI formats
            if parsed_uri.path.startswith("/@"):
                # Mastodon-style URI: https://fosstodon.org/@username
                username = parsed_uri.path[2:]  # Remove the leading /@
                resource = f"acct:{username}@{domain}"
            elif parsed_uri.path.startswith("/users/"):
                # ActivityPub-style URI: https://domain.org/users/username
                username = parsed_uri.path.split("/")[-1]
                resource = f"acct:{username}@{domain}"
            elif "@" in parsed_uri.path:
                # Another Mastodon-style URI: https://domain.org/@username
                username = parsed_uri.path.strip("/").replace("@", "")
                resource = f"acct:{username}@{domain}"
            else:
                # Use the full URI as the resource
                resource = actor_uri

            # Perform WebFinger lookup
            webfinger_url = f"https://{domain}/.well-known/webfinger?resource={urllib.parse.quote(resource)}"
            logger.info(f"WebFinger URL: {webfinger_url}")

            async with httpx.AsyncClient(follow_redirects=True) as client:
                # Set a timeout for the request
                response = await client.get(webfinger_url, timeout=10.0)

                if response.status_code != 200:
                    logger.error(f"WebFinger lookup failed: {response.status_code} {response.text}")
                    # Try a fallback approach for Mastodon instances
                    if "@" in parsed_uri.path:
                        username = parsed_uri.path.strip("/").replace("@", "")
                        return f"https://{domain}/users/{username}/inbox"
                    return None

                webfinger_data = response.json()

                # Find the self link with type application/activity+json
                actor_url = None
                for link in webfinger_data.get("links", []):
                    if link.get("rel") == "self" and link.get("type") == "application/activity+json":
                        actor_url = link.get("href")
                        break

                if not actor_url:
                    logger.error(f"No ActivityPub actor URL found in WebFinger response: {webfinger_data}")
                    # Try a fallback approach for Mastodon instances
                    if "@" in parsed_uri.path:
                        username = parsed_uri.path.strip("/").replace("@", "")
                        return f"https://{domain}/users/{username}/inbox"
                    return None

                # Fetch the actor's profile
                logger.info(f"Fetching actor profile: {actor_url}")
                response = await client.get(
                    actor_url,
                    headers={"Accept": "application/activity+json"},
                    timeout=10.0
                )

                if response.status_code != 200:
                    logger.error(f"Actor profile fetch failed: {response.status_code} {response.text}")
                    return None

                actor_data = response.json()

                # Get the inbox URL
                inbox_url = actor_data.get("inbox")
                if not inbox_url:
                    logger.error(f"No inbox URL found in actor profile: {actor_data}")
                    return None

                logger.info(f"Discovered inbox URL: {inbox_url}")
                # Ensure we're returning a string, not Any
                return str(inbox_url) if inbox_url else None

        except Exception as e:
            logger.exception(f"Error discovering inbox URL: {e}")
            # Try a fallback approach for Mastodon instances
            try:
                parsed_uri = urllib.parse.urlparse(actor_uri)
                domain = parsed_uri.netloc
                if "@" in parsed_uri.path:
                    username = parsed_uri.path.strip("/").replace("@", "")
                    return f"https://{domain}/users/{username}/inbox"
            except Exception:
                pass
            return None

    def _to_dict(self, obj: Any) -> Any:
        """Convert an object to a dictionary."""
        if isinstance(obj, dict):
            return {k: self._to_dict(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._to_dict(item) for item in obj]
        elif dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            # Convert dataclass instance to dict
            result = {}
            # First convert to dict using dataclasses.asdict
            dc_dict = dataclasses.asdict(obj)
            # Then recursively convert all values
            for field_name, field_value in dc_dict.items():
                if field_value is not None:  # Skip None values
                    if field_name == "context":
                        # Special case for @context
                        result["@context"] = self._to_dict(field_value)
                    else:
                        result[field_name] = self._to_dict(field_value)
            return result
        elif isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, ULID):
            return str(obj)
        elif isinstance(obj, (str, int, float, bool, type(None))):
            return obj
        else:
            return str(obj)
