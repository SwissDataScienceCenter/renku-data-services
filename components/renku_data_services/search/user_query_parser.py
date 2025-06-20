"""Parser for the user query ast."""

from __future__ import annotations

import datetime
from typing import Protocol, cast

from parsy import (
    Parser,
    char_from,
    decimal_digit,
    fail,
    from_enum,
    regex,
    seq,
    string,
    success,
    test_char,
)

from renku_data_services.app_config import logging
from renku_data_services.authz.models import Role, Visibility
from renku_data_services.base_models.core import NamespaceSlug
from renku_data_services.search.user_query import (
    Comparison,
    Created,
    CreatedByIs,
    DateTimeCalc,
    DirectMemberIs,
    Field,
    Helper,
    IdIs,
    KeywordIs,
    MemberIs,
    NameIs,
    NamespaceIs,
    Nel,
    Order,
    OrderBy,
    PartialDate,
    PartialDateTime,
    PartialTime,
    RelativeDate,
    RoleIs,
    Segment,
    SlugIs,
    SortableField,
    Text,
    TypeIs,
    UserDef,
    UserId,
    Username,
    UserQuery,
    VisibilityIs,
)
from renku_data_services.solr.entity_documents import EntityType
from renku_data_services.solr.solr_client import SortDirection

logger = logging.getLogger(__name__)


def _check_range(n: int, min: int, max: int, msg: str) -> Parser:
    if n < min or n > max:
        return fail(msg)
    else:
        return success(n)


def _check_month(m: int) -> Parser:
    return _check_range(m, 1, 12, "Expect a month 1-12")


def _check_day(day: int) -> Parser:
    return _check_range(day, 1, 31, "Expect a day 1-31")


def _check_hour(h: int) -> Parser:
    return _check_range(h, 0, 23, "Expect a hour 0-23")


def _check_minute(m: int) -> Parser:
    return _check_range(m, 0, 59, "Expect a minute or second 0-59")


# Parser[DateTimeCalc]
def _create_datetime_calc(args: tuple[PartialDateTime | RelativeDate, str, int]) -> Parser:
    ref: PartialDateTime | RelativeDate = args[0]
    sep: str = args[1]
    days: int = args[2]
    match sep:
        case "+":
            return success(DateTimeCalc(ref, days.__abs__(), False))
        case "-":
            return success(DateTimeCalc(ref, days.__abs__() * -1, False))
        case "/":
            return success(DateTimeCalc(ref, days.__abs__(), True))
        case _:
            return fail(f"Invalid date-time separator: {sep}")


# Parser[FieldTerm]
def _make_field_term(args: tuple[str, Nel[str]]) -> Parser:
    field: str = args[0]
    values: Nel[str] = args[1]
    f = Field(field.lower())
    match f:
        case Field.fname:
            return success(NameIs(values))
        case Field.slug:
            return success(SlugIs(values))
        case Field.id:
            return success(IdIs(values))
        case Field.keyword:
            return success(KeywordIs(values))
        case Field.namespace:
            return success(NamespaceIs(values))
        case Field.created_by:
            return success(CreatedByIs(values))
        case _:
            return fail(f"Invalid field name: {field}")


class _DateTimeParser:
    colon: Parser = string(":")
    dash: Parser = string("-")
    non_zero_digit: Parser = char_from("123456789")
    utcZ: Parser = (string("Z") | string("z")).result(datetime.UTC)

    year: Parser = (non_zero_digit + decimal_digit.times(min=3, max=3).concat()).map(int)
    month: Parser = decimal_digit.times(min=1, max=2).concat().map(int).bind(_check_month)
    dom: Parser = decimal_digit.times(min=1, max=2).concat().map(int).bind(_check_day)
    hour: Parser = decimal_digit.times(min=1, max=2).concat().map(int).bind(_check_hour)
    minsec: Parser = decimal_digit.times(min=1, max=2).concat().map(int).bind(_check_minute)
    ndays: Parser = (non_zero_digit + decimal_digit.many().concat()).map(int) << char_from("dD")

    partial_date: Parser = seq(year, (dash >> month).optional(), (dash >> dom).optional()).combine(PartialDate)
    partial_time: Parser = seq(hour, (colon >> minsec).optional(), (colon >> minsec).optional()).combine(PartialTime)
    partial_datetime: Parser = seq(partial_date, (string("T") >> partial_time).optional(), utcZ.optional()).combine(
        PartialDateTime
    )

    relative_date: Parser = from_enum(RelativeDate, lambda s: s.lower())

    datetime_calc: Parser = seq(partial_datetime | relative_date, char_from("+-/"), ndays).bind(_create_datetime_calc)

    datetime_ref: Parser = datetime_calc | partial_datetime | relative_date


class _ParsePrimitives:
    dp: _DateTimeParser = _DateTimeParser()
    whitespace: Parser = regex(r"\s*")
    comma: Parser = string(",") << whitespace

    char_basic: Parser = test_char(func=Helper.is_valid_char, description="simple string")
    char_esc: Parser = string("\\") >> (string('"') | string("\\"))
    no_quote: Parser = test_char(lambda c: c != '"', description="no quote")

    string_basic: Parser = char_basic.at_least(1).concat()
    string_quoted: Parser = string('"') >> (char_esc | no_quote).at_least(1).concat() << string('"')
    string_value: Parser = string_quoted | string_basic

    string_values: Parser = string_value.sep_by(comma, min=1).map(Nel.unsafe_from_list)

    sortable_field: Parser = from_enum(SortableField, lambda s: s.lower())
    sort_direction: Parser = from_enum(SortDirection, lambda s: s.lower())
    entity_type: Parser = from_enum(EntityType, lambda s: s.lower())
    visibility: Parser = from_enum(Visibility, lambda s: s.lower())
    role: Parser = from_enum(Role, lambda s: s.lower())

    is_equal: Parser = string(Comparison.is_equal.value).result(Comparison.is_equal)
    is_gt: Parser = string(Comparison.is_greater_than).result(Comparison.is_greater_than)
    is_lt: Parser = string(Comparison.is_lower_than).result(Comparison.is_lower_than)
    comparison: Parser = from_enum(Comparison, lambda s: s.lower())

    ordered_by: Parser = seq((sortable_field << string("-")), sort_direction).combine(OrderBy)

    ordered_by_nel: Parser = ordered_by.sep_by(comma, min=1).map(Nel.unsafe_from_list)
    entity_type_nel: Parser = entity_type.sep_by(comma, min=1).map(Nel.unsafe_from_list)
    visibility_nel: Parser = visibility.sep_by(comma, min=1).map(Nel.unsafe_from_list)
    role_nel: Parser = role.sep_by(comma, min=1).map(Nel.unsafe_from_list)
    datetime_ref_nel: Parser = dp.datetime_ref.sep_by(comma, min=1).map(Nel.unsafe_from_list)

    sort_term: Parser = string("sort") >> is_equal >> ordered_by_nel.map(Order)

    type_is: Parser = string(Field.type.value, lambda s: s.lower()) >> is_equal >> entity_type_nel.map(TypeIs)
    visibility_is: Parser = (string(Field.visibility.value, lambda s: s.lower()) >> is_equal >> visibility_nel).map(
        VisibilityIs
    )
    created: Parser = string(Field.created.value, lambda s: s.lower()) >> seq(comparison, datetime_ref_nel).combine(
        Created
    )
    role_is: Parser = string(Field.role.value, lambda s: s.lower()) >> is_equal >> role_nel.map(RoleIs)

    user_name: Parser = string("@") >> string_basic.map(NamespaceSlug.from_name).map(Username)
    user_id: Parser = string_basic.map(UserId)
    user_def_nel: Parser = (user_name | user_id).sep_by(comma, min=1).map(Nel.unsafe_from_list)
    member_is: Parser = string(Field.member.value, lambda s: s.lower()) >> is_equal >> user_def_nel.map(MemberIs)
    direct_member_is: Parser = (
        string(Field.direct_member.value, lambda s: s.lower()) >> is_equal >> user_def_nel.map(DirectMemberIs)
    )

    term_is: Parser = seq(from_enum(Field, lambda s: s.lower()) << is_equal, string_values).bind(_make_field_term)

    field_term: Parser = type_is | visibility_is | role_is | member_is | direct_member_is | created | term_is
    free_text: Parser = test_char(lambda c: not c.isspace(), "string without spaces").at_least(1).concat().map(Text)

    segment: Parser = field_term | sort_term | free_text

    query: Parser = segment.sep_by(whitespace, min=0).map(UserQuery)


class UserQueryTransform(Protocol):
    """Capture transformation to the user query."""

    def visit(self, seg: Segment) -> list[Segment]:
        """Visit a segment.

        Return the empty list to remove the segment or insert other
        segments in the place of the current.
        """
        ...

    def on_end(self) -> list[Segment]:
        """Notify on end."""
        ...

    def __call__(self, uq: UserQuery) -> UserQuery:
        """Apply this transformation to a user query."""
        res: list[Segment] = []
        for seg in uq.segments:
            res.extend(self.visit(seg))

        res.extend(self.on_end())
        return UserQuery(res)

    @classmethod
    def sequence(cls, *args: UserQueryTransform) -> UserQueryTransform:
        """Create a new transformation applying the given ones sequentially."""
        uqt = list(args)
        if len(uqt) == 1:
            return uqt[0]
        else:
            return _SeqUserQueryTransform(uqt)


class _SeqUserQueryTransform(UserQueryTransform):
    def __init__(self, seq: list[UserQueryTransform]) -> None:
        self.__all = seq

    def visit(self, seg: Segment) -> list[Segment]:
        """Visit a segment."""
        lst = [seg]
        for ut in self.__all:
            med = [ut.visit(e) for e in lst]
            lst = [item for sublist in med for item in sublist]

        return lst

    def on_end(self) -> list[Segment]:
        """Notify on end."""
        result = []
        for ut in self.__all:
            result.extend(ut.on_end())
        return result


class _CollapseTexts(UserQueryTransform):
    """Collapses consecutive free text segments.

    It is a bit hard to parse them directly as every term is separated by whitespace.
    """

    def __init__(self) -> None:
        self.__current: Text | None = None

    def visit(self, seg: Segment) -> list[Segment]:
        """Visit a segment."""
        match seg:
            case Text() as t:
                self.__current = t if self.__current is None else self.__current.append(t)
                return []
            case _:
                res: list[Segment] = []
                if self.__current is not None:
                    res.append(self.__current)
                    self.__current = None
                res.append(seg)
                return res

    def on_end(self) -> list[Segment]:
        """Notify on end."""
        cur = self.__current
        if cur is not None:
            self.__current = None
            return [cur]
        else:
            return []


class _CollapseMembers(UserQueryTransform):
    maximum = 4

    def __init__(self) -> None:
        self.__members: list[UserDef] = []
        self.__direct_members: list[UserDef] = []

    def visit(self, seg: Segment) -> list[Segment]:
        match seg:
            case MemberIs() as t:
                self.__members.extend(t.users.to_list())
                return []
            case DirectMemberIs() as t:
                self.__direct_members.extend(t.users.to_list())
                return []
            case _:
                return [seg]

    def on_end(self) -> list[Segment]:
        result: list[Segment] = []
        max = self.maximum
        length = len(self.__members) + len(self.__direct_members)
        if length > max:
            logger.info(f"Removing {length - max} members from query, only {max} allowed!")
            self.__members = self.__members[:max]
            remaining = abs(max - len(self.__members))
            self.__direct_members = self.__direct_members[:remaining]

        nel = Nel.from_list(self.__members)
        if nel is not None:
            result.append(MemberIs(nel))

        nel = Nel.from_list(self.__direct_members)
        if nel is not None:
            result.append(DirectMemberIs(nel))

        self.__members = []
        self.__direct_members = []
        return result


class QueryParser:
    """Parsing user search queries."""

    @classmethod
    def __make_transform(cls) -> UserQueryTransform:
        return UserQueryTransform.sequence(_CollapseMembers(), _CollapseTexts())

    @classmethod
    def parse(cls, input: str) -> UserQuery:
        """Parses a user search query into its ast."""
        pp = _ParsePrimitives()
        res = pp.query.parse(input.strip())
        transform = cls.__make_transform()
        return transform(cast(UserQuery, res))
