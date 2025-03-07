"""AST for a user search query."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as data_field
from enum import StrEnum

from renku_data_services.solr.entity_documents import EntityType
from renku_data_services.solr.solr_client import SortDirection


@dataclass
class Nel[A]:
    """A non empty list."""

    value: A
    more_values: list[A] = data_field(default_factory=list)

    @classmethod
    def of(cls, el: A, *args: A) -> "Nel[A]":
        """Constructor using varargs."""
        return Nel(value=el, more_values=list(args))

    def to_list(self) -> list[A]:
        """Convert to a list."""
        return [self.value] + self.more_values

    def mk_string(self, sep: str, f: Callable[[A], str] = str) -> str:
        """Create a str from all elements mapped over f."""
        return sep.join([f(x) for x in self.to_list()])


class Helper:
    """Internal helper functions."""

    @classmethod
    def quote(cls, input: str) -> str:
        """Wraps input in quotes if necessary."""
        for c in input:
            if c == "," or c == '"' or c.isspace():
                return f'"{input.replace('"', '\"')}"'
        return input


class Field(StrEnum):
    """A field name."""

    id = "id"
    fname = "name"
    slug = "slug"
    visibility = "visibility"
    created = "created"
    created_by = "createdBy"
    type = "type"
    role = "role"
    keyword = "keyword"
    namespace = "namespace"


class Comparison(StrEnum):
    """A comparison for a field."""

    is_equal = ":"
    is_lower_than = "<"
    is_greater_than = ">"


class FieldComparison(ABC):
    """A query part for a specific field."""

    @property
    @abstractmethod
    def field(self) -> Field: ...

    @property
    @abstractmethod
    def cmp(self) -> Comparison: ...

    @abstractmethod
    def _render_value(self) -> str: ...

    def render(self) -> str:
        return f"{self.field.value}{self.cmp.value}{self._render_value()}"


@dataclass
class TypeIs(FieldComparison):
    """Compare the type property against a list of values."""

    values: Nel[EntityType]

    @property
    def field(self) -> Field:
        """The field name."""
        return Field.type

    @property
    def cmp(self) -> Comparison:
        """The comparison operation."""
        return Comparison.is_equal

    def _render_value(self) -> str:
        return self.values.mk_string(",")


@dataclass
class IdIs(FieldComparison):
    """Compare document id against a list of values."""

    values: Nel[str]

    @property
    def field(self) -> Field:
        """The field name."""
        return Field.id

    @property
    def cmp(self) -> Comparison:
        """The comparison operation."""
        return Comparison.is_equal

    def _render_value(self) -> str:
        return self.values.mk_string(",", Helper.quote)


type FieldTerm = TypeIs | IdIs


@dataclass
class Text:
    """A query part that is not corresponding to a specific field."""

    value: str


class SortableField(StrEnum):
    """A field supported for sorting."""

    fname = "name"
    created = "created"
    score = "score"


@dataclass
class OrderBy:
    """A order specification."""

    field: SortableField
    direction: SortDirection

    def render(self) -> str:
        """Renders the string representation."""
        return f"{self.field.value}-{self.direction.value}"


@dataclass
class Order:
    """A query part for defining how to order results."""

    field: OrderBy
    more_fields: list[OrderBy] = data_field(default_factory=list)

    def render(self) -> str:
        """Renders the string version of this query part."""
        if self.more_fields == []:
            return self.field.render()
        else:
            rest = ",".join([x.render() for x in self.more_fields])
            return f"{self.field.render()},{rest}"


type Segment = FieldTerm | Text | Order


@dataclass
class Query:
    """A user search query.

    The list of segments can be empty for the empty query.
    """

    segments: list[Segment]
