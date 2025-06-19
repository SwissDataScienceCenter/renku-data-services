"""AST for a user search query."""

from __future__ import annotations

import calendar
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from dataclasses import field as data_field
from datetime import date, datetime, time, timedelta, tzinfo
from enum import StrEnum
from typing import Any, Self

from renku_data_services.authz.models import Role, Visibility
from renku_data_services.base_models.core import NamespaceSlug
from renku_data_services.namespace.models import UserNamespace
from renku_data_services.solr.entity_documents import EntityType
from renku_data_services.solr.solr_client import SortDirection
from renku_data_services.users.models import UserInfo


@dataclass
class Nel[A]:
    """A non empty list."""

    value: A
    more_values: list[A] = data_field(default_factory=list)

    @classmethod
    def of(cls, el: A, *args: A) -> Nel[A]:
        """Constructor using varargs."""
        return Nel(value=el, more_values=list(args))

    @classmethod
    def unsafe_from_list(cls, els: list[A]) -> Nel[A]:
        """Creates a non-empty list from a list, failing if the argument is empty."""
        return Nel(els[0], els[1:])

    @classmethod
    def from_list(cls, els: list[A]) -> Nel[A] | None:
        """Creates a non-empty list from a list."""
        if els == []:
            return None
        else:
            return cls.unsafe_from_list(els)

    def append(self, other: Self) -> Self:
        """Append other to this list."""
        return self.append_list(other.to_list())

    def append_list(self, other: list[A]) -> Self:
        """Append other to this list."""
        if other == []:
            return self
        else:
            return type(self)(self.value, self.more_values + other)

    def to_list(self) -> list[A]:
        """Convert to a list."""
        return [self.value] + self.more_values

    def mk_string(self, sep: str, f: Callable[[A], str] = str) -> str:
        """Create a str from all elements mapped over f."""
        return sep.join([f(x) for x in self.to_list()])

    def map[B](self, f: Callable[[A], B]) -> Nel[B]:
        """Maps `f` over this list."""
        head = f(self.value)
        rest = [f(x) for x in self.more_values]
        return Nel(head, rest)


class Helper:
    """Internal helper functions."""

    @classmethod
    def is_valid_char(cls, c: str) -> bool:
        """Test for a character that doesn't require quoting."""
        return not c.isspace() and c != '"' and c != "\\" and c != ","

    @classmethod
    def quote(cls, input: str) -> str:
        """Wraps input in quotes if necessary."""
        for c in input:
            if not Helper.is_valid_char(c):
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
    member = "member"
    direct_member = "direct_member"


class Comparison(StrEnum):
    """A comparison for a field."""

    is_equal = ":"
    is_lower_than = "<"
    is_greater_than = ">"


@dataclass
class Username:
    """A user identifier: username slug."""

    slug: NamespaceSlug
    __hashvalue: int | None = field(init=False, repr=False, default=None)

    def render(self) -> str:
        """Render the query part of this value."""
        return f"@{self.slug.value}"

    def __eq__(self, other: Any) -> bool:
        match other:
            case Username() as u:
                return u.slug.value == self.slug.value
            case _:
                return False

    def __hash__(self) -> int:
        if self.__hashvalue is None:
            self.__hashvalue = hash(self.slug.value)

        return self.__hashvalue

    @classmethod
    def from_name(cls, s: str) -> Username:
        """Create a Username from a string."""
        return Username(NamespaceSlug.from_name(s))

    @classmethod
    def from_user_namespace(cls, ns: UserNamespace) -> Username:
        """Create a Username from a UserNamespace."""
        return Username(ns.path.first)

    @classmethod
    def from_user_info(cls, u: UserInfo) -> Username:
        """Create a Username from a UserInfo."""
        return cls.from_user_namespace(u.namespace)


@dataclass
class UserId:
    """A user identifier (the keycloak one)."""

    id: str

    def render(self) -> str:
        """Renders the query representation of this value."""
        return self.id

    def __eq__(self, other: Any) -> bool:
        match other:
            case UserId() as id:
                return id.id == self.id
            case _:
                return False

    def __hash__(self) -> int:
        return hash(self.id)


type UserDef = Username | UserId


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
        return datetime(d.year, d.month, d.day, t.hour, t.minute, t.second, 0, self.zone or default_zone, fold=t.fold)

    def datetime_min(self, default_zone: tzinfo) -> datetime:
        """Set missing parts to the lowest value."""
        d = self.date.min()
        t = (self.time or PartialTime(0)).min()
        return datetime(d.year, d.month, d.day, t.hour, t.minute, t.second, 0, self.zone or default_zone, fold=t.fold)

    def with_zone(self, zone: tzinfo) -> Self:
        """Return a copy with the given zone set."""
        return type(self)(self.date, self.time, zone)

    def resolve(self, ref: datetime, zone: tzinfo) -> tuple[datetime, datetime | None]:
        """Resolve this partial date using the given reference."""
        min = self.datetime_min(zone)
        max = self.datetime_max(zone)
        if min != max:
            return (min, max)
        else:
            return (min, None)


class RelativeDate(StrEnum):
    """A date relative to a reference date."""

    today = "today"
    yesterday = "yesterday"

    def render(self) -> str:
        """Renders the string representation."""
        return self.name

    def resolve(self, ref: datetime, zone: tzinfo) -> tuple[datetime, datetime | None]:
        """Resolve this relative date using the given reference."""
        match self:
            case RelativeDate.today:
                ref_dt = ref
            case RelativeDate.yesterday:
                ref_dt = ref - timedelta(days=1)

        pd = PartialDateTime(PartialDate(ref_dt.year, ref_dt.month, ref_dt.day))
        return pd.resolve(ref, zone)


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

    def resolve(self, ref: datetime, zone: tzinfo) -> tuple[datetime, datetime | None]:
        """Resolve this date calculation using the given reference."""
        (ts_min, ts_max_opt) = self.ref.resolve(ref, zone)
        if self.is_range:
            return (
                ts_min - timedelta(days=self.amount_days),
                (ts_max_opt or ts_min) + timedelta(days=self.amount_days),
            )
        else:
            return (ts_min + timedelta(days=self.amount_days), None)


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
class MemberIs(FieldComparison):
    """Check for membership of a given user."""

    users: Nel[UserDef]

    @property
    def field(self) -> Field:
        """The field name."""
        return Field.member

    @property
    def cmp(self) -> Comparison:
        """The comparison to use."""
        return Comparison.is_equal

    def _render_value(self) -> str:
        return self.users.map(lambda u: u.render()).mk_string(",")


@dataclass
class DirectMemberIs(FieldComparison):
    """Check for direct membership of a given user."""

    users: Nel[UserDef]

    @property
    def field(self) -> Field:
        """The field name."""
        return Field.direct_member

    @property
    def cmp(self) -> Comparison:
        """The comparison to use."""
        return Comparison.is_equal

    def _render_value(self) -> str:
        return self.users.map(lambda u: u.render()).mk_string(",")


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

    @classmethod
    def eq(cls, value: DateTimeRef, *args: DateTimeRef) -> Created:
        """Create an instance with `is_equal` comparison."""
        nel = Nel(value, list(args))
        return Created(Comparison.is_equal, nel)

    @classmethod
    def lt(cls, value: DateTimeRef, *args: DateTimeRef) -> Created:
        """Create an instance with `is_lower_than` comparison."""
        nel = Nel(value, list(args))
        return Created(Comparison.is_lower_than, nel)

    @classmethod
    def gt(cls, value: DateTimeRef, *args: DateTimeRef) -> Created:
        """Create an instance with `is_greater_than` comparison."""
        nel = Nel(value, list(args))
        return Created(Comparison.is_greater_than, nel)


@dataclass
class RoleIs(FieldComparison):
    """Compare a role."""

    values: Nel[Role]

    @property
    def field(self) -> Field:
        """The field name."""
        return Field.role

    @property
    def cmp(self) -> Comparison:
        """The comparison operation."""
        return Comparison.is_equal

    def _render_value(self) -> str:
        return self.values.mk_string(",")


@dataclass
class Text:
    """A query part that is not corresponding to a specific field."""

    value: str

    def render(self) -> str:
        """Return the value."""
        return self.value

    def append(self, next: Self) -> Self:
        """Appends a text to this one."""
        if self.value == "":
            return next
        elif next.value == "":
            return self
        else:
            return type(self)(self.value + " " + next.value)


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

    @classmethod
    def from_tuple(cls, t: tuple[SortableField, SortDirection]) -> OrderBy:
        """Create an OrderBy value from a tuple."""
        return OrderBy(t[0], t[1])

    def render(self) -> str:
        """Renders the string representation."""
        return f"{self.field.value}-{self.direction.value}"


@dataclass
class Order:
    """A query part for defining how to order results."""

    fields: Nel[OrderBy]

    def render(self) -> str:
        """Renders the string version of this query part."""
        return f"sort:{self.fields.mk_string(",", lambda e: e.render())}"

    def append(self, other: Self) -> Self:
        """Append the field list of `other` to this."""
        return type(self)(self.fields.append(other.fields))


type FieldTerm = (
    TypeIs
    | IdIs
    | NameIs
    | SlugIs
    | VisibilityIs
    | KeywordIs
    | NamespaceIs
    | CreatedByIs
    | Created
    | RoleIs
    | MemberIs
    | DirectMemberIs
)


type Segment = FieldTerm | Text | Order


class Segments:
    """Helpers for creating segments."""

    @classmethod
    def text(cls, text: str) -> Segment:
        """Return a free text query segment."""
        return Text(text)

    @classmethod
    def sort_by(cls, s: tuple[SortableField, SortDirection], *args: tuple[SortableField, SortDirection]) -> Segment:
        """Return a sort query segment."""
        rest = list(map(OrderBy.from_tuple, args))
        return Order(Nel(OrderBy.from_tuple(s), rest))

    @classmethod
    def type_is(cls, et: EntityType, *args: EntityType) -> Segment:
        """Return type-is query segment."""
        return TypeIs(Nel(et, list(args)))

    @classmethod
    def id_is(cls, id: str, *args: str) -> Segment:
        """Return id-is query segment."""
        return IdIs(Nel(id, list(args)))

    @classmethod
    def name_is(cls, name: str, *args: str) -> Segment:
        """Return name-is query segment."""
        return NameIs(Nel(name, list(args)))

    @classmethod
    def slug_is(cls, slug: str, *args: str) -> Segment:
        """Return slug-is query segment."""
        return SlugIs(Nel(slug, list(args)))

    @classmethod
    def visibility_is(cls, vis: Visibility, *args: Visibility) -> Segment:
        """Return visibility-is query segment."""
        return VisibilityIs(Nel(vis, list(args)))

    @classmethod
    def keyword_is(cls, kw: str, *args: str) -> Segment:
        """Return keyword-is query segment."""
        return KeywordIs(Nel(kw, list(args)))

    @classmethod
    def namespace_is(cls, ns: str, *args: str) -> Segment:
        """Return namespace-is query segment."""
        return NamespaceIs(Nel(ns, list(args)))

    @classmethod
    def created_by_is(cls, id: str, *args: str) -> Segment:
        """Return created_by-is query segment."""
        return CreatedByIs(Nel(id, list(args)))

    @classmethod
    def created(cls, cmp: Comparison, date: DateTimeRef, *args: DateTimeRef) -> Segment:
        """Return created query segment."""
        return Created(cmp, Nel(date, list(args)))

    @classmethod
    def created_is(cls, date: DateTimeRef, *args: DateTimeRef) -> Segment:
        """Return created-is query segment."""
        return cls.created(Comparison.is_equal, date, *args)

    @classmethod
    def created_is_lt(cls, date: DateTimeRef, *args: DateTimeRef) -> Segment:
        """Return created-< query segment."""
        return cls.created(Comparison.is_lower_than, date, *args)

    @classmethod
    def created_is_gt(cls, date: DateTimeRef, *args: DateTimeRef) -> Segment:
        """Return created-> query segment."""
        return cls.created(Comparison.is_greater_than, date, *args)

    @classmethod
    def role_is(cls, role: Role, *args: Role) -> Segment:
        """Return role-is query segment."""
        return RoleIs(Nel(role, list(args)))


@dataclass
class UserQuery:
    """A user search query.

    The list of segments can be empty for the empty query.
    """

    segments: list[Segment]

    @classmethod
    def of(cls, *args: Segment) -> UserQuery:
        """Constructor using varargs."""
        return UserQuery(list(args))

    def render(self) -> str:
        """Return the string representation of this query."""
        return " ".join([e.render() for e in self.segments])

    def extract_order(self) -> tuple[list[FieldTerm | Text], Order | None]:
        """Extracts all sort segments into a single OrderBy value."""
        segs: list[FieldTerm | Text] = []
        orders: list[OrderBy] = []
        for s in self.segments:
            match s:
                case Order() as o:
                    orders.extend(o.fields.to_list())

                case f:
                    segs.append(f)

        sort = Nel.from_list(orders)
        return (segs, Order(sort) if sort is not None else None)
