"""API specification for ActivityPub."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, HttpUrl


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
    PROJECT = "Project"


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


class Link(BaseModel):
    """ActivityPub Link object."""

    href: HttpUrl
    rel: Optional[str] = None
    mediaType: Optional[str] = None
    name: Optional[str] = None
    hreflang: Optional[str] = None
    height: Optional[int] = None
    width: Optional[int] = None
    preview: Optional[Dict[str, Any]] = None


class PublicKey(BaseModel):
    """ActivityPub PublicKey object."""

    id: HttpUrl
    owner: HttpUrl
    publicKeyPem: str


class BaseObject(BaseModel):
    """Base ActivityPub Object."""

    context: List[str] = Field(default_factory=lambda: ["https://www.w3.org/ns/activitystreams"], alias="@context")
    id: HttpUrl
    type: Union[ObjectType, ActorType, ActivityType, str]
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


class Actor(BaseObject):
    """ActivityPub Actor."""

    type: ActorType
    preferredUsername: str
    inbox: HttpUrl
    outbox: HttpUrl
    followers: Optional[HttpUrl] = None
    following: Optional[HttpUrl] = None
    liked: Optional[HttpUrl] = None
    publicKey: Optional[PublicKey] = None
    endpoints: Optional[Dict[str, Any]] = None
    icon: Optional[Union[Dict[str, Any], Link]] = None
    image: Optional[Union[Dict[str, Any], Link]] = None


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


class Object(BaseObject):
    """ActivityPub Object."""

    type: ObjectType
    attachment: Optional[List[Union[Dict[str, Any], Link]]] = None
    inReplyTo: Optional[Union[str, Dict[str, Any]]] = None
    location: Optional[Union[str, Dict[str, Any]]] = None
    tag: Optional[List[Union[Dict[str, Any], Link]]] = None
    duration: Optional[str] = None


class Activity(BaseObject):
    """ActivityPub Activity."""

    type: ActivityType
    actor: Union[str, Actor]
    object: Optional[Union[str, Dict[str, Any], "Activity", BaseObject]] = None
    target: Optional[Union[str, Dict[str, Any], "Activity", BaseObject]] = None
    result: Optional[Union[str, Dict[str, Any], "Activity", BaseObject]] = None
    origin: Optional[Union[str, Dict[str, Any], "Activity", BaseObject]] = None
    instrument: Optional[Union[str, Dict[str, Any], "Activity", BaseObject]] = None


class OrderedCollection(BaseObject):
    """ActivityPub OrderedCollection."""

    type: str = "OrderedCollection"
    totalItems: int
    first: Optional[HttpUrl] = None
    last: Optional[HttpUrl] = None


class OrderedCollectionPage(BaseObject):
    """ActivityPub OrderedCollectionPage."""

    type: str = "OrderedCollectionPage"
    totalItems: int
    orderedItems: List[Union[Activity, Object]]
    next: Optional[HttpUrl] = None
    prev: Optional[HttpUrl] = None
    partOf: Optional[HttpUrl] = None


class WebFingerLink(BaseModel):
    """WebFinger Link."""

    rel: str
    type: Optional[str] = None
    href: Optional[HttpUrl] = None
    template: Optional[str] = None


class WebFingerResponse(BaseModel):
    """WebFinger Response."""

    subject: str
    aliases: Optional[List[str]] = None
    links: List[WebFingerLink]


class NodeInfoLink(BaseModel):
    """NodeInfo Link."""

    rel: str
    href: HttpUrl


class NodeInfoLinks(BaseModel):
    """NodeInfo Links."""

    links: List[NodeInfoLink]


class NodeInfoSoftware(BaseModel):
    """NodeInfo Software."""

    name: str
    version: str


class NodeInfoUsers(BaseModel):
    """NodeInfo Users."""

    total: int


class NodeInfoUsage(BaseModel):
    """NodeInfo Usage."""

    users: NodeInfoUsers
    localPosts: Optional[int] = None


class NodeInfoServices(BaseModel):
    """NodeInfo Services."""

    inbound: List[str] = Field(default_factory=list)
    outbound: List[str] = Field(default_factory=list)


class NodeInfo(BaseModel):
    """NodeInfo."""

    version: str = "2.0"
    software: NodeInfoSoftware
    protocols: List[str] = Field(default_factory=lambda: ["activitypub"])
    services: NodeInfoServices = Field(default_factory=NodeInfoServices)
    usage: NodeInfoUsage
    openRegistrations: bool
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ProjectFollowers(BaseModel):
    """Project followers."""

    followers: List[str]


class Error(BaseModel):
    """Error response."""

    error: str
    message: str
