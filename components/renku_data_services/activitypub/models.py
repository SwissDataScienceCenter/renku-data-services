"""Models for ActivityPub."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from ulid import ULID

from renku_data_services.base_models.core import APIUser
from renku_data_services.project.models import Project


class ActivityType(str, Enum):
    """ActivityPub activity types."""

    CREATE = "Create"
    UPDATE = "Update"
    DELETE = "Delete"
    FOLLOW = "Follow"
    ACCEPT = "Accept"
    REJECT = "Reject"
    ANNOUNCE = "Announce"
    LIKE = "Like"
    UNDO = "Undo"


class ActorType(str, Enum):
    """ActivityPub actor types."""

    PERSON = "Person"
    SERVICE = "Service"
    GROUP = "Group"
    ORGANIZATION = "Organization"
    APPLICATION = "Application"
    PROJECT = "Project"  # Custom type for Renku projects


class ObjectType(str, Enum):
    """ActivityPub object types."""

    NOTE = "Note"
    ARTICLE = "Article"
    COLLECTION = "Collection"
    DOCUMENT = "Document"
    IMAGE = "Image"
    VIDEO = "Video"
    AUDIO = "Audio"
    PAGE = "Page"
    EVENT = "Event"
    PLACE = "Place"
    PROFILE = "Profile"
    TOMBSTONE = "Tombstone"


@dataclass
class Link:
    """ActivityPub Link object."""

    href: str
    rel: Optional[str] = None
    mediaType: Optional[str] = None
    name: Optional[str] = None
    hreflang: Optional[str] = None
    height: Optional[int] = None
    width: Optional[int] = None
    preview: Optional[Dict[str, Any]] = None


@dataclass
class BaseObject:
    """Base ActivityPub Object."""

    id: str
    type: Union[ObjectType, ActorType, ActivityType, str]
    context: List[str] = field(default_factory=lambda: ["https://www.w3.org/ns/activitystreams"])
    name: Optional[str] = None
    summary: Optional[str] = None
    content: Optional[str] = None
    url: Optional[Union[str, List[str], Link, List[Link]]] = None
    published: Optional[datetime] = None
    updated: Optional[datetime] = None
    mediaType: Optional[str] = None
    attributedTo: Optional[Union[str, Dict[str, Any]]] = None
    to: Optional[List[str]] = None
    cc: Optional[List[str]] = None
    bto: Optional[List[str]] = None
    bcc: Optional[List[str]] = None


@dataclass
class Actor(BaseObject):
    """ActivityPub Actor."""

    type: ActorType
    inbox: Optional[str] = None
    outbox: Optional[str] = None
    preferredUsername: Optional[str] = None
    followers: Optional[str] = None
    following: Optional[str] = None
    liked: Optional[str] = None
    publicKey: Optional[Dict[str, Any]] = None
    endpoints: Optional[Dict[str, Any]] = None
    icon: Optional[Union[Dict[str, Any], Link]] = None
    image: Optional[Union[Dict[str, Any], Link]] = None


@dataclass
class ProjectActor(Actor):
    """ActivityPub representation of a Renku Project as an Actor."""

    type: ActorType = ActorType.PROJECT
    keywords: Optional[List[str]] = None
    repositories: Optional[List[str]] = None
    visibility: Optional[str] = None
    created_by: Optional[str] = None
    creation_date: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    documentation: Optional[str] = None

    @classmethod
    def from_project(cls, project: Project, base_url: str, domain: str) -> "ProjectActor":
        """Create a ProjectActor from a Project."""
        project_id = f"{base_url}/ap/projects/{project.id}"
        username = f"{project.namespace.slug}_{project.slug}"

        # Set the audience based on visibility
        to = ["https://www.w3.org/ns/activitystreams#Public"] if project.visibility.value == "public" else []

        # Set the attributedTo to the user who created the project
        attributed_to = f"{base_url}/ap/users/{project.created_by}"

        # Create public key info
        public_key = None  # This would be populated with actual key data

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

        return cls(
            id=project_id,
            name=project.name,
            preferredUsername=username,
            summary=project.description,
            content=project.description,
            documentation=project.documentation,
            attributedTo=attributed_to,
            to=to,
            url=f"{base_url}/projects/{project.namespace.slug}/{project.slug}",
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
            icon=icon,
        )


@dataclass
class Activity(BaseObject):
    """ActivityPub Activity."""

    type: ActivityType
    actor: Optional[Union[str, Actor]] = None
    object: Optional[Union[str, Dict[str, Any], "Activity", BaseObject]] = None
    target: Optional[Union[str, Dict[str, Any], "Activity", BaseObject]] = None
    result: Optional[Union[str, Dict[str, Any], "Activity", BaseObject]] = None
    origin: Optional[Union[str, Dict[str, Any], "Activity", BaseObject]] = None
    instrument: Optional[Union[str, Dict[str, Any], "Activity", BaseObject]] = None


@dataclass
class Object(BaseObject):
    """ActivityPub Object."""

    type: ObjectType
    attachment: Optional[List[Union[Dict[str, Any], Link]]] = None
    inReplyTo: Optional[Union[str, Dict[str, Any]]] = None
    location: Optional[Union[str, Dict[str, Any]]] = None
    tag: Optional[List[Union[Dict[str, Any], Link]]] = None
    duration: Optional[str] = None


@dataclass
class UnsavedActivityPubActor:
    """An ActivityPub actor that hasn't been stored in the database."""

    username: str
    name: Optional[str] = None
    summary: Optional[str] = None
    type: ActorType = ActorType.SERVICE
    user_id: Optional[str] = None
    project_id: Optional[ULID] = None


@dataclass
class ActivityPubActor:
    """An ActivityPub actor that has been stored in the database."""

    id: ULID
    username: str
    name: Optional[str]
    summary: Optional[str]
    type: ActorType
    user_id: Optional[str]
    project_id: Optional[ULID]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC).replace(microsecond=0))
    updated_at: Optional[datetime] = None
    private_key_pem: Optional[str] = None
    public_key_pem: Optional[str] = None


@dataclass
class UnsavedActivityPubFollower:
    """An ActivityPub follower that hasn't been stored in the database."""

    actor_id: ULID
    follower_actor_uri: str
    accepted: bool = False


@dataclass
class ActivityPubFollower:
    """An ActivityPub follower that has been stored in the database."""

    id: ULID
    actor_id: ULID
    follower_actor_uri: str
    accepted: bool
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC).replace(microsecond=0))
    updated_at: Optional[datetime] = None


@dataclass
class ActivityPubConfig:
    """Configuration for ActivityPub."""

    domain: str
    base_url: str
    admin_email: str
