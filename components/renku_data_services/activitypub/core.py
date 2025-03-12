"""Business logic for ActivityPub."""

import json
import logging
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional, Union
import urllib.parse

import httpx
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives import hashes, serialization
import base64

from ulid import ULID

from renku_data_services import errors
from renku_data_services.activitypub import models
from renku_data_services.activitypub.db import ActivityPubRepository
from renku_data_services.base_models.core import APIUser
from renku_data_services.project.db import ProjectRepository
from renku_data_services.project.models import Project


logger = logging.getLogger(__name__)


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
        actor = await self.activitypub_repo.get_or_create_project_actor(user=user, project_id=project_id)

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
        )

    async def get_project_followers(self, user: APIUser, project_id: ULID) -> List[str]:
        """Get the followers of a project."""
        # Get the actor
        actor = await self.activitypub_repo.get_or_create_project_actor(user=user, project_id=project_id)

        # Get the followers
        followers = await self.activitypub_repo.get_followers(actor_id=actor.id)

        # Return only accepted followers
        return [follower.follower_actor_uri for follower in followers if follower.accepted]

    async def handle_follow(self, user: APIUser, project_id: ULID, follower_actor_uri: str) -> models.Activity:
        """Handle a follow request for a project."""
        # Get the actor
        actor = await self.activitypub_repo.get_or_create_project_actor(user=user, project_id=project_id)

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

        # Send the Accept activity to the follower's inbox
        await self._deliver_activity(actor, accept_activity, follower_actor_uri + "/inbox")

        return accept_activity

    async def handle_unfollow(self, user: APIUser, project_id: ULID, follower_actor_uri: str) -> None:
        """Handle an unfollow request for a project."""
        # Get the actor
        actor = await self.activitypub_repo.get_or_create_project_actor(user=user, project_id=project_id)

        # Remove the follower
        await self.activitypub_repo.remove_follower(actor_id=actor.id, follower_actor_uri=follower_actor_uri)

    async def announce_project_update(self, user: APIUser, project_id: ULID) -> None:
        """Announce a project update to followers."""
        # Get the actor
        actor = await self.activitypub_repo.get_or_create_project_actor(user=user, project_id=project_id)

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
                await self._deliver_activity(actor, update_activity, follower_uri + "/inbox")
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

        # Prepare the request
        headers = await self._build_signature_headers(actor, inbox_url, activity_dict)

        # Send the request
        async with httpx.AsyncClient() as client:
            response = await client.post(
                inbox_url,
                json=activity_dict,
                headers=headers,
            )

            if response.status_code >= 400:
                logger.error(f"Failed to deliver activity to {inbox_url}: {response.status_code} {response.text}")
                raise errors.ExternalServiceError(
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

    def _to_dict(self, obj: Any) -> Dict[str, Any]:
        """Convert an object to a dictionary."""
        if isinstance(obj, dict):
            return {k: self._to_dict(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._to_dict(item) for item in obj]
        elif hasattr(obj, "__dataclass_fields__"):
            # It's a dataclass
            result = {}
            for field_name in obj.__dataclass_fields__:
                value = getattr(obj, field_name)
                if value is not None:  # Skip None values
                    if field_name == "context":
                        # Special case for @context
                        result["@context"] = self._to_dict(value)
                    else:
                        result[field_name] = self._to_dict(value)
            return result
        elif isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, ULID):
            return str(obj)
        elif isinstance(obj, (str, int, float, bool, type(None))):
            return obj
        else:
            return str(obj)
