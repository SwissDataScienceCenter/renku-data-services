"""Defines the entity documents used with Solr."""

from abc import abstractmethod
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import AliasChoices, BaseModel, BeforeValidator, Field, field_serializer, field_validator
from ulid import ULID

from renku_data_services.authz.models import Visibility
from renku_data_services.base_models.core import Slug
from renku_data_services.solr.solr_client import DocVersion, ResponseBody


def _str_to_slug(value: Any) -> Any:
    if isinstance(value, str):
        return Slug.from_name(value)
    else:
        return value


class EntityType(StrEnum):
    """The different type of entities available from search."""

    project = "Project"
    user = "User"
    group = "Group"


class EntityDoc(BaseModel, frozen=True):
    """Base class for entity document models."""

    namespace: Annotated[Slug, BeforeValidator(_str_to_slug)]
    version: int = Field(
        serialization_alias="_version_",
        validation_alias=AliasChoices("version", "_version_"),
        default=DocVersion.not_exists.value,
    )
    score: float | None = None

    @abstractmethod
    def entity_type(self) -> EntityType:
        """Return the type of this entity."""
        ...

    def to_dict(self) -> dict[str, Any]:
        """Return the dict of this group."""
        dict = self.model_dump(by_alias=True, exclude_defaults=True)
        # note: _kind=fullentity is for being backwards compatible, it might not be needed in the future
        dict.update(_type=self.entity_type().value, _kind="fullentity")
        return dict

    def reset_solr_fields(self) -> Self:
        """Resets fields that are filled by solr when querying."""
        return self.model_copy(update={"version": DocVersion.not_exists.value, "score": None})


class User(EntityDoc, frozen=True):
    """Represents a renku user in SOLR."""

    id: str
    firstName: str | None = None
    lastName: str | None = None

    def entity_type(self) -> EntityType:
        """Return the type of this entity."""
        return EntityType.user

    @field_serializer("namespace", when_used="always")
    def __serialize_namespace(self, namespace: Slug) -> str:
        return namespace.value

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "User":
        """Create a User from a dictionary."""
        return User.model_validate(d)


class Group(EntityDoc, frozen=True):
    """Represents a renku user in SOLR."""

    id: ULID
    name: str
    description: str | None = None

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
    def from_dict(cls, d: dict[str, Any]) -> "Group":
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
    def from_dict(cls, d: dict[str, Any]) -> "Project":
        """Create a Project from a dictionary."""
        return Project.model_validate(d)
