"""AST for a user search query."""

from __future__ import annotations

import calendar
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from dataclasses import field as data_field
from datetime import date, datetime, time, timedelta, tzinfo
from enum import StrEnum
from typing import Self, override

from renku_data_services.authz.models import Role, Visibility
from renku_data_services.base_models.core import NamespaceSlug
from renku_data_services.base_models.nel import Nel
from renku_data_services.namespace.models import UserNamespace
from renku_data_services.solr.entity_documents import EntityType
from renku_data_services.solr.solr_client import SortDirection
from renku_data_services.users.models import UserInfo


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
                return f'"{input.replace('"', '\\"')}"'
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
    direct_member = "direct_member"
    inherited_member = "inherited_member"
    doi = "doi"
    publisher_name = "publisher_name"


class Comparison(StrEnum):
    """A comparison for a field."""

    is_equal = ":"
    is_lower_than = "<"
    is_greater_than = ">"


@dataclass(eq=True, frozen=True)
class Username:
    """A user identifier: username slug."""

    slug: NamespaceSlug
    __hashvalue: int | None = field(init=False, repr=False, default=None)

    def render(self) -> str:
        """Render the query part of this value."""
        return f"@{self.slug.value}"

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


@dataclass(eq=True, frozen=True)
class UserId:
    """A user identifier (the keycloak one)."""

    id: str

    def render(self) -> str:
        """Renders the query representation of this value."""
        return self.id


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

    def max(self) -> PartialDate:
        """Set missing parts to the maximum value."""
        m = self.month or 12
        (_, dom) = calendar.monthrange(self.year, m)
        return PartialDate(self.year, m, self.dayOfMonth or dom)

    def min(self) -> PartialDate:
        """Set missing parts to the lowest value."""
        return PartialDate(
            self.year,
            self.month or 1,
            self.dayOfMonth or 1,
        )

    def date_max(self) -> date:
        """Set missing parts to the maximum value."""
        dm = self.max()
        return date(dm.year, dm.month or 0, dm.dayOfMonth or 0)

    def date_min(self) -> date:
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

    def max(self) -> PartialTime:
        """Set missing parts to the highest value."""
        return PartialTime(self.hour, self.minute or 59, self.second or 59)

    def min(self) -> PartialTime:
        """Set missing parts to the lowest value."""
        return PartialTime(self.hour, self.minute or 0, self.second or 0)

    def time_max(self) -> time:
        """Set missing parts to the highest value."""
        return time(self.hour, self.minute or 59, self.second or 59)

    def time_min(self) -> time:
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

    def max(self) -> PartialDateTime:
        """Set missing parts to the highest value."""
        return PartialDateTime(self.date.max(), (self.time or PartialTime(23)).max())

    def min(self) -> PartialDateTime:
        """Set missing parts to the lowest value."""
        return PartialDateTime(self.date.min(), (self.time or PartialTime(0)).min())

    def datetime_max(self, default_zone: tzinfo) -> datetime:
        """Set missing parts to the highest value."""
        d = self.date.date_max()
        t = (self.time or PartialTime(23, 59, 59)).time_max()
        return datetime(d.year, d.month, d.day, t.hour, t.minute, t.second, 0, self.zone or default_zone, fold=t.fold)

    def datetime_min(self, default_zone: tzinfo) -> datetime:
        """Set missing parts to the lowest value."""
        d = self.date.date_min()
        t = (self.time or PartialTime(0)).time_min()
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


class SegmentBase(ABC):
    """Base class for a query segment."""

    @abstractmethod
    async def accept(self, visitor: SegmentVisitior) -> None:
        """Apply this to the visitor."""
        ...


class FieldComparison(SegmentBase):
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
class InheritedMemberIs(FieldComparison):
    """Check for membership of a given user."""

    users: Nel[UserDef]

    @property
    def field(self) -> Field:
        """The field name."""
        return Field.inherited_member

    @property
    def cmp(self) -> Comparison:
        """The comparison to use."""
        return Comparison.is_equal

    def _render_value(self) -> str:
        return self.users.map(lambda u: u.render()).mk_string(",")

    async def accept(self, visitor: SegmentVisitior) -> None:
        """Apply this to the visitor."""
        return await visitor.visit_inherited_member_is(self)


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

    async def accept(self, visitor: SegmentVisitior) -> None:
        """Apply this to the visitor."""
        return await visitor.visit_direct_member_is(self)


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

    async def accept(self, visitor: SegmentVisitior) -> None:
        """Apply this to the visitor."""
        return await visitor.visit_type_is(self)


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

    async def accept(self, visitor: SegmentVisitior) -> None:
        """Apply this to the visitor."""
        return await visitor.visit_id_is(self)


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

    async def accept(self, visitor: SegmentVisitior) -> None:
        """Apply this to the visitor."""
        return await visitor.visit_name_is(self)


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

    async def accept(self, visitor: SegmentVisitior) -> None:
        """Apply this to the visitor."""
        return await visitor.visit_slug_is(self)


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

    async def accept(self, visitor: SegmentVisitior) -> None:
        """Apply this to the visitor."""
        return await visitor.visit_keyword_is(self)


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

    async def accept(self, visitor: SegmentVisitior) -> None:
        """Apply this to the visitor."""
        return await visitor.visit_namespace_is(self)


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

    async def accept(self, visitor: SegmentVisitior) -> None:
        """Apply this to the visitor."""
        return await visitor.visit_visibility_is(self)


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

    async def accept(self, visitor: SegmentVisitior) -> None:
        """Apply this to the visitor."""
        return await visitor.visit_created_by_is(self)


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

    async def accept(self, visitor: SegmentVisitior) -> None:
        """Apply this to the visitor."""
        return await visitor.visit_created(self)


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

    async def accept(self, visitor: SegmentVisitior) -> None:
        """Apply this to the visitor."""
        return await visitor.visit_role_is(self)


@dataclass
class DoiIs(FieldComparison):
    """Compare the doi against a list of values."""

    values: Nel[str]

    @property
    def field(self) -> Field:
        """The field name."""
        return Field.doi

    @property
    def cmp(self) -> Comparison:
        """The comparison operation."""
        return Comparison.is_equal

    def _render_value(self) -> str:
        return self.values.mk_string(",", Helper.quote)

    async def accept(self, visitor: SegmentVisitior) -> None:
        """Apply this to the visitor."""
        return await visitor.visit_doi_is(self)


@dataclass
class PublisherNameIs(FieldComparison):
    """Compare the publisher name against a list of values."""

    values: Nel[str]

    @property
    def field(self) -> Field:
        """The field name."""
        return Field.publisher_name

    @property
    def cmp(self) -> Comparison:
        """The comparison operation."""
        return Comparison.is_equal

    def _render_value(self) -> str:
        return self.values.mk_string(",", Helper.quote)

    async def accept(self, visitor: SegmentVisitior) -> None:
        """Apply this to the visitor."""
        return await visitor.visit_publisher_name_is(self)


@dataclass
class Text(SegmentBase):
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

    async def accept(self, visitor: SegmentVisitior) -> None:
        """Apply this to the visitor."""
        return await visitor.visit_text(self)


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
class Order(SegmentBase):
    """A query part for defining how to order results."""

    fields: Nel[OrderBy]

    def render(self) -> str:
        """Renders the string version of this query part."""
        return f"sort:{self.fields.mk_string(",", lambda e: e.render())}"

    def append(self, other: Self) -> Self:
        """Append the field list of `other` to this."""
        return type(self)(self.fields.append(other.fields))

    async def accept(self, visitor: SegmentVisitior) -> None:
        """Apply this to the visitor."""
        return await visitor.visit_order(self)


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
    | InheritedMemberIs
    | DirectMemberIs
    | DoiIs
    | PublisherNameIs
)


type Segment = FieldTerm | Text | Order


class Segments:
    """Helpers for creating segments."""

    @classmethod
    def order(cls, o: OrderBy, *args: OrderBy) -> Segment:
        """Return an order segment."""
        return Order(Nel(o, list(args)))

    @classmethod
    def inherited_member_is(cls, user: UserDef, *args: UserDef) -> Segment:
        """Return member-is query segment."""
        return InheritedMemberIs(Nel(user, list(args)))

    @classmethod
    def direct_member_is(cls, user: UserDef, *args: UserDef) -> Segment:
        """Return member-is query segment."""
        return DirectMemberIs(Nel(user, list(args)))

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

    @classmethod
    def doi_is(cls, doi: str, *args: str) -> Segment:
        """Return doi-is query segment."""
        return DoiIs(Nel(doi, list(args)))

    @classmethod
    def publisher_name_is(cls, publisher_name: str, *args: str) -> Segment:
        """Return publisher-name-is query segment."""
        return PublisherNameIs(Nel(publisher_name, list(args)))


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

    async def accept[T](self, visitor: UserQueryVisitor[T]) -> T:
        """Apply the visitor."""
        for s in self.segments:
            await s.accept(visitor)
        return await visitor.build()

    async def transform(self, visitor: UserQueryVisitor[UserQuery], *args: UserQueryVisitor[UserQuery]) -> UserQuery:
        """Apply this query to the given transformations sequentially."""
        transforms: list[UserQueryVisitor[UserQuery]] = [visitor]
        transforms.extend(list(args))

        acc = self
        [acc := await acc.accept(t) for t in transforms]
        return acc


class SegmentVisitior(ABC):
    """A visitor for a query segment."""

    @abstractmethod
    async def visit_order(self, order: Order) -> None:
        """Visit order."""
        ...

    @abstractmethod
    async def visit_text(self, text: Text) -> None:
        """Visit text."""
        ...

    @abstractmethod
    async def visit_type_is(self, ft: TypeIs) -> None:
        """Visit type-is."""
        ...

    @abstractmethod
    async def visit_id_is(self, ft: IdIs) -> None:
        """Visit id-is."""
        ...

    @abstractmethod
    async def visit_name_is(self, ft: NameIs) -> None:
        """Visit name-is."""
        ...

    @abstractmethod
    async def visit_slug_is(self, ft: SlugIs) -> None:
        """Visit slug-is."""
        ...

    @abstractmethod
    async def visit_visibility_is(self, ft: VisibilityIs) -> None:
        """Visit visibility-is."""
        ...

    @abstractmethod
    async def visit_keyword_is(self, ft: KeywordIs) -> None:
        """Visit keyword-is."""
        ...

    @abstractmethod
    async def visit_namespace_is(self, ft: NamespaceIs) -> None:
        """Visit namespace-is."""
        ...

    @abstractmethod
    async def visit_created_by_is(self, ft: CreatedByIs) -> None:
        """Visit created-by-is."""
        ...

    @abstractmethod
    async def visit_created(self, ft: Created) -> None:
        """Visit created."""
        ...

    @abstractmethod
    async def visit_role_is(self, ft: RoleIs) -> None:
        """Visit role-is."""
        ...

    @abstractmethod
    async def visit_direct_member_is(self, ft: DirectMemberIs) -> None:
        """Visit direct-member-is."""
        ...

    @abstractmethod
    async def visit_inherited_member_is(self, ft: InheritedMemberIs) -> None:
        """Visit inherited-member-is."""
        ...

    @abstractmethod
    async def visit_doi_is(self, ft: DoiIs) -> None:
        """Visit doi-is."""
        ...

    @abstractmethod
    async def visit_publisher_name_is(self, ft: PublisherNameIs) -> None:
        """Visit doi-is."""
        ...


class UserQueryVisitor[T](SegmentVisitior):
    """A visitor to transform user queries."""

    @abstractmethod
    async def build(self) -> T:
        """Return the value."""
        ...


class UserQueryFieldTermVisitor[T](UserQueryVisitor[T]):
    """A variant of a visitor dispatching on the base union type Segment.

    Every concrete visit_ method forwards to the `visit_field_term` method.
    """

    @abstractmethod
    async def visit_field_term(self, ft: FieldTerm) -> None:
        """Visit a field term query segment."""
        ...

    @override
    async def visit_created(self, ft: Created) -> None:
        """Forwards to `visit_field_term`."""
        return await self.visit_field_term(ft)

    @override
    async def visit_created_by_is(self, ft: CreatedByIs) -> None:
        """Forwards to `visit_field_term`."""
        return await self.visit_field_term(ft)

    @override
    async def visit_direct_member_is(self, ft: DirectMemberIs) -> None:
        """Forwards to `visit_field_term`."""
        return await self.visit_field_term(ft)

    @override
    async def visit_id_is(self, ft: IdIs) -> None:
        """Forwards to `visit_field_term`."""
        return await self.visit_field_term(ft)

    @override
    async def visit_keyword_is(self, ft: KeywordIs) -> None:
        """Forwards to `visit_field_term`."""
        return await self.visit_field_term(ft)

    @override
    async def visit_inherited_member_is(self, ft: InheritedMemberIs) -> None:
        """Forwards to `visit_field_term`."""
        return await self.visit_field_term(ft)

    @override
    async def visit_name_is(self, ft: NameIs) -> None:
        """Forwards to `visit_field_term`."""
        return await self.visit_field_term(ft)

    @override
    async def visit_namespace_is(self, ft: NamespaceIs) -> None:
        """Forwards to `visit_field_term`."""
        return await self.visit_field_term(ft)

    @override
    async def visit_role_is(self, ft: RoleIs) -> None:
        """Forwards to `visit_field_term`."""
        return await self.visit_field_term(ft)

    @override
    async def visit_slug_is(self, ft: SlugIs) -> None:
        """Forwards to `visit_field_term`."""
        return await self.visit_field_term(ft)

    @override
    async def visit_type_is(self, ft: TypeIs) -> None:
        """Forwards to `visit_field_term`."""
        return await self.visit_field_term(ft)

    @override
    async def visit_visibility_is(self, ft: VisibilityIs) -> None:
        """Forwards to `visit_field_term`."""
        return await self.visit_field_term(ft)

    @override
    async def visit_doi_is(self, ft: DoiIs) -> None:
        """Forwards to `visit_field_term`."""
        return await self.visit_field_term(ft)

    @override
    async def visit_publisher_name_is(self, ft: PublisherNameIs) -> None:
        """Forwards to `visit_field_term`."""
        return await self.visit_field_term(ft)


class EmptyUserQueryVisitor[T](UserQueryFieldTermVisitor[T]):
    """A visitor with every method doing nothing.

    The `build` method is left to implement by subclasses.
    """

    @override
    async def visit_field_term(self, ft: FieldTerm) -> None:
        """Visit field-term node."""
        return None

    @override
    async def visit_order(self, order: Order) -> None:
        """Visit order node."""
        return None

    @override
    async def visit_text(self, text: Text) -> None:
        """Visit text node."""
        return None
