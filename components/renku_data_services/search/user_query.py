"""AST for a user search query."""

import calendar
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as data_field
from datetime import date, datetime, time, tzinfo
from enum import StrEnum
from typing import Self

from renku_data_services.authz.models import Visibility
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

    @classmethod
    def unsafe_from_list(cls, els: list[A]) -> "Nel[A]":
        """Creates a non-empty list from a list, failing if the argument is empty."""
        return Nel(els[0], els[1:])

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
                return f'"{input.replace('"', '"')}"'
        return input


class Field(StrEnum):
    """A field name."""

    id = "id"
    fname = "name"
    slug = "slug"
    visibility = "visibility"
    created = "created"
    created_by = "createdby"
    type = "type"
    role = "role"
    keyword = "keyword"
    namespace = "namespace"


class Comparison(StrEnum):
    """A comparison for a field."""

    is_equal = ":"
    is_lower_than = "<"
    is_greater_than = ">"


@dataclass
class PartialDate:
    """A date where month and day may be omitted."""

    year: int
    month: int | None = data_field(default=None)
    dayOfMonth: int | None = data_field(default=None)

    def render(self) -> str:
        """Return the string representation."""
        res = f"{self.year}"
        if self.month is not None:
            res += f"-{self.month:02}"
        if self.dayOfMonth is not None:
            res += f"-{self.dayOfMonth:02}"
        return res

    def is_exact(self) -> bool:
        """Return whether all optional parts are set."""
        return self.month is not None and self.dayOfMonth is not None

    def max(self) -> date:
        """Set missing parts to the maximum value."""
        m = self.month or 12
        (_, dom) = calendar.monthrange(self.year, m)
        return date(self.year, m, self.dayOfMonth or dom)

    def min(self) -> date:
        """Set missing parts to the lowest value."""
        return date(
            self.year,
            self.month or 1,
            self.dayOfMonth or 1,
        )


@dataclass
class PartialTime:
    """A time where minutes and seconds are optional."""

    hour: int
    minute: int | None = data_field(default=None)
    second: int | None = data_field(default=None)

    def render(self) -> str:
        """Renders the string representation."""
        res = f"{self.hour:02}"
        if self.minute is not None:
            res += f":{self.minute:02}"
        if self.second is not None:
            res += f":{self.second:02}"
        return res

    def max(self) -> time:
        """Set missing parts to the highest value."""
        return time(self.hour, self.minute or 59, self.second or 59)

    def min(self) -> time:
        """Set missing parts to the lowest value."""
        return time(self.hour, self.minute or 0, self.second or 0)


@dataclass
class PartialDateTime:
    """A date time, where minor fields are optional."""

    date: PartialDate
    time: PartialTime | None = data_field(default=None)
    zone: tzinfo | None = data_field(default=None)

    def render(self) -> str:
        """Renders the string representation."""
        res = self.date.render()
        if self.time is not None:
            res += f"T{self.time.render()}"
        if self.zone is not None:
            res += ""
        return res

    def datetime_max(self, default_zone: tzinfo) -> datetime:
        """Set missing parts to the highest value."""
        d = self.date.max()
        t = (self.time or PartialTime(23, 59, 59)).max()
        return datetime(
            d.year, d.month, d.day, t.hour, t.minute, t.second, t.microsecond, self.zone or default_zone, fold=t.fold
        )

    def datetime_min(self, default_zone: tzinfo) -> datetime:
        """Set missing parts to the lowest value."""
        d = self.date.min()
        t = (self.time or PartialTime(0)).min()
        return datetime(
            d.year, d.month, d.day, t.hour, t.minute, t.second, t.microsecond, self.zone or default_zone, fold=t.fold
        )

    def with_zone(self, zone: tzinfo) -> Self:
        """Return a copy with the given zone set."""
        return type(self)(self.date, self.time, zone)


class RelativeDate(StrEnum):
    """A date relative to a reference date."""

    today = "today"
    yesterday = "yesterday"

    def render(self) -> str:
        """Renders the string representation."""
        return self.name


@dataclass
class DateTimeCalc:
    """A date specification using calculation from a reference date."""

    ref: PartialDateTime | RelativeDate
    amount_days: int
    is_range: bool

    def render(self) -> str:
        """Renders the string representation."""
        period = self.amount_days.__abs__()
        sep = "+"
        if self.is_range:
            sep = "/"
        if self.amount_days < 0:
            sep = "-"

        return f"{self.ref.render()}{sep}{period}d"


type DateTimeRef = PartialDateTime | RelativeDate | DateTimeCalc


class FieldComparison(ABC):
    """A query part for a specific field."""

    @property
    @abstractmethod
    def field(self) -> Field:
        """The field to compare."""
        ...

    @property
    @abstractmethod
    def cmp(self) -> Comparison:
        """The comparision to use."""
        ...

    @abstractmethod
    def _render_value(self) -> str: ...

    def render(self) -> str:
        """Renders the string representation."""
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


@dataclass
class NameIs(FieldComparison):
    """Compare the name against a list of values."""

    values: Nel[str]

    @property
    def field(self) -> Field:
        """The field name."""
        return Field.fname

    @property
    def cmp(self) -> Comparison:
        """The comparison operation."""
        return Comparison.is_equal

    def _render_value(self) -> str:
        return self.values.mk_string(",", Helper.quote)


@dataclass
class SlugIs(FieldComparison):
    """Compare the slug against a list of values."""

    values: Nel[str]

    @property
    def field(self) -> Field:
        """The field name."""
        return Field.slug

    @property
    def cmp(self) -> Comparison:
        """The comparison operation."""
        return Comparison.is_equal

    def _render_value(self) -> str:
        return self.values.mk_string(",", Helper.quote)


@dataclass
class KeywordIs(FieldComparison):
    """Compare the keyword against a list of values."""

    values: Nel[str]

    @property
    def field(self) -> Field:
        """The field name."""
        return Field.keyword

    @property
    def cmp(self) -> Comparison:
        """The comparison operation."""
        return Comparison.is_equal

    def _render_value(self) -> str:
        return self.values.mk_string(",", Helper.quote)


@dataclass
class NamespaceIs(FieldComparison):
    """Compare the keyword against a list of values."""

    values: Nel[str]

    @property
    def field(self) -> Field:
        """The field name."""
        return Field.namespace

    @property
    def cmp(self) -> Comparison:
        """The comparison operation."""
        return Comparison.is_equal

    def _render_value(self) -> str:
        return self.values.mk_string(",", Helper.quote)


@dataclass
class VisibilityIs(FieldComparison):
    """Compare the visiblity against a list of values."""

    values: Nel[Visibility]

    @property
    def field(self) -> Field:
        """The field name."""
        return Field.visibility

    @property
    def cmp(self) -> Comparison:
        """The comparison operation."""
        return Comparison.is_equal

    def _render_value(self) -> str:
        return self.values.mk_string(",")


@dataclass
class CreatedByIs(FieldComparison):
    """Compare the keyword against a list of values."""

    values: Nel[str]

    @property
    def field(self) -> Field:
        """The field name."""
        return Field.created_by

    @property
    def cmp(self) -> Comparison:
        """The comparison operation."""
        return Comparison.is_equal

    def _render_value(self) -> str:
        return self.values.mk_string(",", Helper.quote)


@dataclass
class Created(FieldComparison):
    """Compare the created timestamp."""

    cmp_op: Comparison
    values: Nel[DateTimeRef]

    @property
    def field(self) -> Field:
        """The field name."""
        return Field.created

    @property
    def cmp(self) -> Comparison:
        """The comparison operation."""
        return self.cmp_op

    def _render_value(self) -> str:
        return self.values.mk_string(",", lambda e: e.render())


type FieldTerm = TypeIs | IdIs | NameIs | SlugIs | VisibilityIs | KeywordIs | NamespaceIs | CreatedByIs | Created


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

    fields: Nel[OrderBy]

    def render(self) -> str:
        """Renders the string version of this query part."""
        return self.fields.mk_string(",", lambda e: e.render())


type Segment = FieldTerm | Text | Order


@dataclass
class Query:
    """A user search query.

    The list of segments can be empty for the empty query.
    """

    segments: list[Segment]
