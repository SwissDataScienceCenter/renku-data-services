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
from renku_data_services.base_models.core import (
    DataConnectorSlug,
    NamespacePath,
    NamespaceSlug,
    ProjectPath,
    ProjectSlug,
    ResourceType,
    Slug,
)
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
    dataconnector = "DataConnector"

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
            case EntityType.dataconnector:
                return ResourceType.data_connector


class EntityDoc(BaseModel, ABC, frozen=True):
    """Base class for an entity."""

    path: str
    slug: Annotated[Slug, BeforeValidator(_str_to_slug)]
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

    @field_serializer("slug", when_used="always")
    def __serialize_slug(self, slug: Slug) -> str:
        return slug.value

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
    isNamespace: Annotated[Literal[True], BeforeValidator(lambda e: True)] = True

    @property
    def entity_type(self) -> EntityType:
        """Return the type of this entity."""
        return EntityType.user

    @classmethod
    def of(cls, id: str, slug: Slug, firstName: str | None = None, lastName: str | None = None) -> User:
        """Create a new user from the given data."""
        return User(path=slug.value, slug=slug, id=id, firstName=firstName, lastName=lastName)

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
    isNamespace: Annotated[Literal[True], BeforeValidator(lambda e: True)] = True

    @property
    def entity_type(self) -> EntityType:
        """Return the type of this entity."""
        return EntityType.group

    @field_serializer("id", when_used="always")
    def __serialize_id(self, id: ULID) -> str:
        return str(id)

    @classmethod
    def of(cls, id: ULID, slug: Slug, name: str, description: str | None = None) -> Group:
        """Create a new group from the given data."""
        return Group(path=slug.value, slug=slug, id=id, description=description, name=name)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Group:
        """Create a Group from a dictionary."""
        return Group.model_validate(d)


class Project(EntityDoc, frozen=True):
    """Represents a renku project in SOLR."""

    id: ULID
    name: str
    visibility: Visibility
    namespace_path: str = Field(
        serialization_alias="namespacePath",
        validation_alias=AliasChoices("namespace_path", "namespacePath"),
    )
    createdBy: str
    creationDate: datetime
    repositories: list[str] = Field(default_factory=list)
    description: str | None = None
    keywords: list[str] = Field(default_factory=list)
    isNamespace: Annotated[Literal[True], BeforeValidator(lambda e: True)] = True
    namespaceDetails: ResponseBody | None = None
    creatorDetails: ResponseBody | None = None

    @property
    def entity_type(self) -> EntityType:
        """Return the type of this entity."""
        return EntityType.project

    @field_validator("keywords")
    @classmethod
    def _sort_keywords(cls, v: list[str]) -> list[str]:
        v.sort()
        return v

    @field_serializer("id", when_used="always")
    def __serialize_id(self, id: ULID) -> str:
        return str(id)

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

    def in_namespace(self, ns: Group | User) -> Project:
        """Set the namespace as given, returning a new object."""
        p_slug = ProjectSlug(self.slug.value)
        parent = NamespacePath(NamespaceSlug(ns.slug.value))
        path = (parent / p_slug).serialize()
        return self.model_copy(update={"path": path, "namespace_path": ns.path})

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Project:
        """Create a Project from a dictionary."""
        return Project.model_validate(d)


class DataConnector(EntityDoc, frozen=True):
    """Represents a global or non-global renku data connector in SOLR."""

    id: ULID
    namespace_path: str | None = Field(
        serialization_alias="namespacePath",
        validation_alias=AliasChoices("namespace_path", "namespacePath"),
        default=None,
    )
    name: str
    storageType: str
    readonly: bool
    visibility: Visibility
    createdBy: str
    creationDate: datetime
    description: str | None = None
    keywords: list[str] = Field(default_factory=list)
    isNamespace: Annotated[Literal[False], BeforeValidator(lambda e: False)] = False
    namespaceDetails: ResponseBody | None = None
    creatorDetails: ResponseBody | None = None
    publisherName: str | None = None
    doi: str | None = None

    @property
    def entity_type(self) -> EntityType:
        """Return the type of this entity."""
        return EntityType.dataconnector

    @field_validator("keywords")
    @classmethod
    def _sort_keywords(cls, v: list[str]) -> list[str]:
        v.sort()
        return v

    @field_serializer("id", when_used="always")
    def __serialize_id(self, id: ULID) -> str:
        return str(id)

    @field_serializer("visibility", when_used="always")
    def __serialize_visibilty(self, visibility: Visibility) -> str:
        return visibility.value

    @field_serializer("creationDate", when_used="always")
    def __serialize_creation_date(self, creationDate: datetime) -> str:
        return creationDate.strftime("%Y-%m-%dT%H:%M:%SZ")

    def in_namespace(self, ns: Group | User | Project | None) -> DataConnector:
        """Set the namespace as given, returning a new object."""
        ns_path = ns.path if ns is not None else None
        dc_slug = DataConnectorSlug(self.slug.value)

        # I want to reuse the `"/".join(…)` to combine namespace + slug
        match ns:
            case Group() as g:
                parent: NamespacePath | ProjectPath | None = NamespacePath(NamespaceSlug(g.slug.value))
            case User() as u:
                parent = NamespacePath(NamespaceSlug(u.slug.value))
            case Project() as p:
                parent = ProjectPath(NamespaceSlug(p.namespace_path), ProjectSlug(p.slug.value))
            case None:
                parent = None

        path = (parent / dc_slug).serialize() if parent is not None else self.slug.value
        return self.model_copy(update={"path": path, "namespace_path": ns_path})

    @field_validator("creationDate")
    @classmethod
    def _add_tzinfo(cls, v: datetime) -> datetime:
        return v.replace(tzinfo=UTC)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DataConnector:
        """Create a data connector from a dictionary."""
        return DataConnector.model_validate(d)


class EntityDocReader:
    """Reads dicts into one of the entity document classes."""

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> User | Project | Group | DataConnector | None:
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
                case EntityType.dataconnector:
                    return DataConnector.from_dict(doc)
