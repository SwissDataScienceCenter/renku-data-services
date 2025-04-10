"""Defines the entity documents used with Solr."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AliasChoices,
    BaseModel,
    BeforeValidator,
    Field,
    errors,
    field_serializer,
    field_validator,
)
from ulid import ULID

from renku_data_services.authz.models import Visibility
from renku_data_services.base_models.core import ResourceType, Slug
from renku_data_services.solr.entity_schema import Fields
from renku_data_services.solr.solr_client import DocVersion, DocVersions, ResponseBody


def _str_to_slug(value: Any) -> Slug:
    if isinstance(value, str):
        return Slug.from_name(value)
    elif isinstance(value, Slug):
        return value
    raise errors.ValidationError(message="converting to slug in solr documents was not successful")


def _str_to_visibility_public(value: Any) -> Literal[Visibility.PUBLIC]:
    if isinstance(value, str) and value.lower() == "public":
        return Visibility.PUBLIC
    else:
        raise ValueError(f"Expected visibility public, got: {value}")


class EntityType(StrEnum):
    """The different type of entities available from search."""

    project = "Project"
    user = "User"
    group = "Group"
    data_connector = "DataConnector"

    @property
    def to_resource_type(self) -> ResourceType:
        """Map this entity-type to the core resource type."""
        match self:
            case EntityType.project:
                return ResourceType.project
            case EntityType.user:
                return ResourceType.user
            case EntityType.group:
                return ResourceType.group


class EntityDoc(BaseModel, ABC, frozen=True):
    """Base class for entity document models."""

    namespace: Annotated[Slug, BeforeValidator(_str_to_slug)]
    version: DocVersion = Field(
        serialization_alias="_version_",
        validation_alias=AliasChoices("version", "_version_"),
        default_factory=DocVersions.not_exists,
    )
    score: float | None = None

    @property
    @abstractmethod
    def entity_type(self) -> EntityType:
        """Return the type of this entity."""
        ...

    def to_dict(self) -> dict[str, Any]:
        """Return the dict of this group."""
        dict = self.model_dump(by_alias=True, exclude_none=True, mode="json")
        # note: _kind=fullentity is for being backwards compatible, it might not be needed in the future
        dict.update(_type=self.entity_type.value, _kind="fullentity")
        return dict

    def reset_solr_fields(self) -> Self:
        """Resets fields that are filled by solr when querying."""
        return self.model_copy(update={"version": DocVersions.not_exists(), "score": None})


class User(EntityDoc, frozen=True):
    """Represents a renku user in SOLR."""

    id: str
    firstName: str | None = None
    lastName: str | None = None
    visibility: Annotated[Literal[Visibility.PUBLIC], BeforeValidator(_str_to_visibility_public)] = Visibility.PUBLIC

    @property
    def entity_type(self) -> EntityType:
        """Return the type of this entity."""
        return EntityType.user

    @field_serializer("namespace", when_used="always")
    def __serialize_namespace(self, namespace: Slug) -> str:
        return namespace.value

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> User:
        """Create a User from a dictionary."""
        return User.model_validate(d)


class Group(EntityDoc, frozen=True):
    """Represents a renku user in SOLR."""

    id: ULID
    name: str
    description: str | None = None
    visibility: Annotated[Literal[Visibility.PUBLIC], BeforeValidator(_str_to_visibility_public)] = Visibility.PUBLIC

    @property
    def entity_type(self) -> EntityType:
        """Return the type of this entity."""
        return EntityType.group

    @field_serializer("id", when_used="always")
    def __serialize_id(self, id: ULID) -> str:
        return str(id)

    @field_serializer("namespace", when_used="always")
    def __serialize_namespace(self, namespace: Slug) -> str:
        return namespace.value

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Group:
        """Create a Group from a dictionary."""
        return Group.model_validate(d)


class Project(EntityDoc, frozen=True):
    """Represents a renku project in SOLR."""

    id: ULID
    name: str
    slug: Annotated[Slug, BeforeValidator(_str_to_slug)]
    visibility: Visibility
    createdBy: str
    creationDate: datetime
    repositories: list[str] = Field(default_factory=list)
    description: str | None = None
    keywords: list[str] = Field(default_factory=list)
    namespaceDetails: ResponseBody | None = None
    creatorDetails: ResponseBody | None = None

    @property
    def entity_type(self) -> EntityType:
        """Return the type of this entity."""
        return EntityType.project

    @field_serializer("namespace", when_used="always")
    def __serialize_namespace(self, namespace: Slug) -> str:
        return namespace.value

    @field_serializer("id", when_used="always")
    def __serialize_id(self, id: ULID) -> str:
        return str(id)

    @field_serializer("slug", when_used="always")
    def __serialize_slug(self, slug: Slug) -> str:
        return slug.value

    @field_serializer("visibility", when_used="always")
    def __serialize_visibilty(self, visibility: Visibility) -> str:
        return visibility.value

    @field_serializer("creationDate", when_used="always")
    def __serialize_creation_date(self, creationDate: datetime) -> str:
        return creationDate.strftime("%Y-%m-%dT%H:%M:%SZ")

    @field_validator("creationDate")
    @classmethod
    def _add_tzinfo(cls, v: datetime) -> datetime:
        return v.replace(tzinfo=UTC)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Project:
        """Create a Project from a dictionary."""
        return Project.model_validate(d)


class DataConnector(EntityDoc, frozen=True):
    """Represents a renku data connector in SOLR."""

    id: ULID
    project_id: ULID | None
    name: str
    slug: Annotated[Slug, BeforeValidator(_str_to_slug)]
    visibility: Visibility
    createdBy: str
    creationDate: datetime
    description: str | None = None
    keywords: list[str] = Field(default_factory=list)
    namespaceDetails: ResponseBody | None = None
    creatorDetails: ResponseBody | None = None

    @property
    def entity_type(self) -> EntityType:
        """Return the type of this entity."""
        return EntityType.data_connector

    @field_serializer("namespace", when_used="always")
    def __serialize_namespace(self, namespace: Slug) -> str:
        return namespace.value

    @field_serializer("id", when_used="always")
    def __serialize_id(self, id: ULID) -> str:
        return str(id)

    @field_serializer("slug", when_used="always")
    def __serialize_slug(self, slug: Slug) -> str:
        return slug.value

    @field_serializer("visibility", when_used="always")
    def __serialize_visibilty(self, visibility: Visibility) -> str:
        return visibility.value

    @field_serializer("creationDate", when_used="always")
    def __serialize_creation_date(self, creationDate: datetime) -> str:
        return creationDate.strftime("%Y-%m-%dT%H:%M:%SZ")

    @field_validator("creationDate")
    @classmethod
    def _add_tzinfo(cls, v: datetime) -> datetime:
        return v.replace(tzinfo=UTC)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Project:
        """Create a Project from a dictionary."""
        return Project.model_validate(d)

class EntityDocReader:
    """Reads dicts into one of the entity document classes."""

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> User | Project | Group | None:
        """Reads dicts into one of the entity document classes."""
        dt = doc.get(Fields.entity_type)
        if dt is None:
            return None
        else:
            discriminator = EntityType[dt.lower()]
            match discriminator:
                case EntityType.project:
                    return Project.from_dict(doc)
                case EntityType.user:
                    return User.from_dict(doc)
                case EntityType.group:
                    return Group.from_dict(doc)
