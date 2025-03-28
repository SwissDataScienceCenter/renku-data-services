"""Parser for the user query ast."""

import datetime
from typing import cast

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

from renku_data_services.authz.models import Role, Visibility
from renku_data_services.search.user_query import (
    Comparison,
    Created,
    CreatedByIs,
    DateTimeCalc,
    Field,
    FieldTerm,
    Helper,
    IdIs,
    KeywordIs,
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
    UserQuery,
    VisibilityIs,
)
from renku_data_services.solr.entity_documents import EntityType
from renku_data_services.solr.solr_client import SortDirection


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


def _create_datetime_calc(ref: PartialDateTime | RelativeDate, sep: str, days: int) -> DateTimeCalc:
    match sep:
        case "+":
            return DateTimeCalc(ref, days.__abs__(), False)
        case "-":
            return DateTimeCalc(ref, days.__abs__() * -1, False)
        case "/":
            return DateTimeCalc(ref, days.__abs__(), True)
        case _:
            raise


def _make_field_term(field: str, values: Nel[str]) -> FieldTerm:
    f = Field(field.lower())
    match f:
        case Field.fname:
            return NameIs(values)
        case Field.slug:
            return SlugIs(values)
        case Field.id:
            return IdIs(values)
        case Field.keyword:
            return KeywordIs(values)
        case Field.namespace:
            return NamespaceIs(values)
        case Field.created_by:
            return CreatedByIs(values)
        case _:
            raise Exception(f"invalid field name: {field}")


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

    datetime_calc: Parser = seq(partial_datetime | relative_date, char_from("+-/"), ndays).combine(
        _create_datetime_calc
    )

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
    term_is: Parser = seq(from_enum(Field, lambda s: s.lower()) << is_equal, string_values).combine(_make_field_term)

    field_term: Parser = type_is | visibility_is | role_is | created | term_is
    free_text: Parser = test_char(lambda c: not c.isspace(), "string without spaces").at_least(1).concat().map(Text)

    segment: Parser = field_term | sort_term | free_text

    query: Parser = segment.sep_by(whitespace, min=0).map(UserQuery)


class QueryParser:
    """Parsing user search queries."""

    @classmethod
    def __collapse_text(cls, q: UserQuery) -> UserQuery:
        """Collapses consecutive free text segments.

        It is a bit hard to parse them directly as every term is separated by whitespace.
        """
        result: list[Segment] = []
        current: Text | None = None
        for s in q.segments:
            match s:
                case Text() as t:
                    current = t if current is None else current.append(t)
                case _:
                    if current is not None:
                        result.append(current)
                        current = None
                    result.append(s)

        if current is not None:
            result.append(current)

        return UserQuery(result)

    @classmethod
    def parse(cls, input: str) -> UserQuery:
        """Parses a user search query into its ast."""
        pp = _ParsePrimitives()
        res = pp.query.parse(input.strip())
        return cls.__collapse_text(cast(UserQuery, res))
