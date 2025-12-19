"""Tests for the query parser."""

import datetime
import random
import string

import pytest
from parsy import ParseError

from renku_data_services.authz.models import Role, Visibility
from renku_data_services.base_models.nel import Nel
from renku_data_services.search.user_query import (
    Comparison,
    Created,
    CreatedByIs,
    DateTimeCalc,
    DirectMemberIs,
    DoiIs,
    IdIs,
    InheritedMemberIs,
    KeywordIs,
    NameIs,
    NamespaceIs,
    Order,
    OrderBy,
    PartialDate,
    PartialDateTime,
    PartialTime,
    PublisherNameIs,
    RelativeDate,
    RoleIs,
    SlugIs,
    SortableField,
    Text,
    TypeIs,
    UserId,
    Username,
    UserQuery,
    VisibilityIs,
)
from renku_data_services.search.user_query import (
    Segments as S,
)
from renku_data_services.search.user_query_parser import QueryParser, _DateTimeParser, _ParsePrimitives
from renku_data_services.solr.entity_documents import EntityType
from renku_data_services.solr.solr_client import SortDirection

pp = _ParsePrimitives()


def test_user_name() -> None:
    assert pp.user_name.parse("@hello") == Username.from_name("hello")
    assert pp.user_name.parse("@test.me") == Username.from_name("test.me")
    with pytest.raises(ParseError):
        pp.user_name.parse("help")
    with pytest.raises(ParseError):
        pp.user_name.parse("@t - a")


def test_inherited_member_is() -> None:
    assert pp.inherited_member_is.parse("inherited_member:@hello") == InheritedMemberIs(
        Nel(Username.from_name("hello"))
    )
    assert pp.inherited_member_is.parse("inherited_member:hello") == InheritedMemberIs(Nel(UserId("hello")))


def test_direct_member_is() -> None:
    assert pp.direct_member_is.parse("direct_member:@hello") == DirectMemberIs(Nel(Username.from_name("hello")))
    assert pp.direct_member_is.parse("direct_member:hello") == DirectMemberIs(Nel(UserId("hello")))


def test_sortable_field() -> None:
    for field in SortableField._member_map_.values():
        assert pp.sortable_field.parse(field.value) == field

    with pytest.raises(ParseError):
        pp.sortable_field.parse("")
    with pytest.raises(ParseError):
        pp.sortable_field.parse("abc")


def test_sort_direction() -> None:
    for field in SortDirection._member_map_.values():
        assert pp.sort_direction.parse(field.value) == field
    with pytest.raises(ParseError):
        pp.sort_direction.parse("")
    with pytest.raises(ParseError):
        pp.sort_direction.parse("abc")


def test_order_by() -> None:
    for sf in SortableField._member_map_.values():
        for dir in SortDirection._member_map_.values():
            value = OrderBy(sf, dir)  # type: ignore
            assert pp.ordered_by.parse(value.render()) == value
    with pytest.raises(ParseError):
        pp.ordered_by.parse("")
    with pytest.raises(ParseError):
        pp.ordered_by.parse("name")
    with pytest.raises(ParseError):
        pp.ordered_by.parse("name-")
    with pytest.raises(ParseError):
        pp.ordered_by.parse("name-abc")
    with pytest.raises(ParseError):
        pp.ordered_by.parse("name - desc")


def test_sort_term() -> None:
    assert pp.sort_term.parse("sort:name-desc") == Order(Nel(OrderBy(SortableField.fname, SortDirection.desc)))
    assert pp.sort_term.parse("sort:score-asc,name-desc") == Order(
        Nel.of(OrderBy(SortableField.score, SortDirection.asc), OrderBy(SortableField.fname, SortDirection.desc))
    )


def test_entity_type() -> None:
    for field in EntityType._member_map_.values():
        assert pp.entity_type.parse(field.value) == field
        assert pp.entity_type.parse(field.value.lower()) == field
        assert pp.entity_type.parse(field.value.upper()) == field


def test_entity_type_nel() -> None:
    value = EntityType.project.value
    assert pp.entity_type_nel.parse(value) == Nel(EntityType.project)

    value = "Project,Group"
    assert pp.entity_type_nel.parse(value) == Nel.of(EntityType.project, EntityType.group)


def test_order_by_nel() -> None:
    value = "name-asc,created-desc"
    assert pp.ordered_by_nel.parse(value) == Nel.of(
        OrderBy(SortableField.fname, SortDirection.asc),
        OrderBy(SortableField.created, SortDirection.desc),
    )
    value = "name-asc, created-desc"
    assert pp.ordered_by_nel.parse(value) == Nel.of(
        OrderBy(SortableField.fname, SortDirection.asc),
        OrderBy(SortableField.created, SortDirection.desc),
    )

    value = "created-desc"
    assert pp.ordered_by_nel.parse(value) == Nel(
        OrderBy(SortableField.created, SortDirection.desc),
    )

    with pytest.raises(ParseError):
        pp.ordered_by_nel.parse("")


def test_comparisons() -> None:
    assert pp.is_equal.parse(":") == Comparison.is_equal
    assert pp.is_gt.parse(">") == Comparison.is_greater_than
    assert pp.is_lt.parse("<") == Comparison.is_lower_than


def test_type_is() -> None:
    assert pp.type_is.parse("type:Project") == TypeIs(Nel(EntityType.project))
    assert pp.type_is.parse("type:Project,Group") == TypeIs(Nel.of(EntityType.project, EntityType.group))
    assert pp.type_is.parse("type:Project, Group") == TypeIs(Nel.of(EntityType.project, EntityType.group))


def test_visibilty_is() -> None:
    assert pp.visibility_is.parse("visibility:public") == VisibilityIs(Nel.of(Visibility.PUBLIC))
    assert pp.visibility_is.parse("visibility:private") == VisibilityIs(Nel.of(Visibility.PRIVATE))
    assert pp.visibility_is.parse("visibility:Public") == VisibilityIs(Nel.of(Visibility.PUBLIC))
    assert pp.visibility_is.parse("visibility:Private") == VisibilityIs(Nel.of(Visibility.PRIVATE))


def test_created() -> None:
    assert pp.created.parse("created<today") == Created(Comparison.is_lower_than, Nel.of(RelativeDate.today))
    assert pp.created.parse("created>today") == Created(Comparison.is_greater_than, Nel.of(RelativeDate.today))
    assert pp.created.parse("created:today") == Created(Comparison.is_equal, Nel.of(RelativeDate.today))
    assert pp.created.parse("created>today-7d") == Created(
        Comparison.is_greater_than, Nel.of(DateTimeCalc(RelativeDate.today, -7, False))
    )


def test_role_is() -> None:
    assert pp.role_is.parse("role:owner") == RoleIs(Nel(Role.OWNER))
    assert pp.role_is.parse("role:viewer") == RoleIs(Nel(Role.VIEWER))
    assert pp.role_is.parse("role:editor") == RoleIs(Nel(Role.EDITOR))
    assert pp.role_is.parse("role:viewer,editor") == RoleIs(Nel.of(Role.VIEWER, Role.EDITOR))


def test_field_term() -> None:
    assert pp.field_term.parse("created<today") == Created(Comparison.is_lower_than, Nel.of(RelativeDate.today))
    assert pp.field_term.parse("visibility:public") == VisibilityIs(Nel.of(Visibility.PUBLIC))
    assert pp.field_term.parse("type:Project") == TypeIs(Nel(EntityType.project))
    assert pp.field_term.parse("name:test") == NameIs(Nel("test"))
    assert pp.field_term.parse("slug:test") == SlugIs(Nel("test"))
    assert pp.field_term.parse("id:test") == IdIs(Nel("test"))
    assert pp.field_term.parse("keyword:test") == KeywordIs(Nel("test"))
    assert pp.field_term.parse("namespace:test") == NamespaceIs(Nel("test"))
    assert pp.field_term.parse("createdBy:test") == CreatedByIs(Nel("test"))
    assert pp.field_term.parse("role:owner") == RoleIs(Nel(Role.OWNER))
    assert pp.field_term.parse("role:viewer") == RoleIs(Nel(Role.VIEWER))
    assert pp.field_term.parse("direct_member:@john") == DirectMemberIs(Nel(Username.from_name("john")))
    assert pp.field_term.parse("direct_member:123-456") == DirectMemberIs(Nel(UserId("123-456")))
    assert pp.field_term.parse("inherited_member:@john") == InheritedMemberIs(Nel(Username.from_name("john")))
    assert pp.field_term.parse("inherited_member:123-456") == InheritedMemberIs(Nel(UserId("123-456")))
    assert pp.field_term.parse("doi:10.16904/envidat.714") == DoiIs(Nel("10.16904/envidat.714"))
    assert pp.field_term.parse("publisher_name:EnviDat") == PublisherNameIs(Nel("EnviDat"))


def test_free_text() -> None:
    assert pp.free_text.parse("just") == Text("just")

    with pytest.raises(ParseError):
        pp.free_text.parse("")

    with pytest.raises(ParseError):
        pp.free_text.parse('"hello world"')


def test_segment() -> None:
    assert pp.segment.parse("abcdefg") == Text("abcdefg")
    assert pp.segment.parse("created<today") == Created(Comparison.is_lower_than, Nel.of(RelativeDate.today))
    assert pp.segment.parse("created>today-7d") == Created(
        Comparison.is_greater_than, Nel(DateTimeCalc(RelativeDate.today, -7, False))
    )
    assert pp.segment.parse("visibility:public") == VisibilityIs(Nel.of(Visibility.PUBLIC))
    assert pp.segment.parse("type:Project") == TypeIs(Nel(EntityType.project))
    assert pp.segment.parse("name:test") == NameIs(Nel("test"))
    assert pp.segment.parse("slug:test") == SlugIs(Nel("test"))
    assert pp.segment.parse("id:test") == IdIs(Nel("test"))
    assert pp.segment.parse("keyword:test") == KeywordIs(Nel("test"))
    assert pp.segment.parse("namespace:test") == NamespaceIs(Nel("test"))
    assert pp.segment.parse("createdBy:test") == CreatedByIs(Nel("test"))
    assert pp.segment.parse("direct_member:@john") == DirectMemberIs(Nel(Username.from_name("john")))
    assert pp.segment.parse("direct_member:123-456") == DirectMemberIs(Nel(UserId("123-456")))
    assert pp.segment.parse("inherited_member:@john") == InheritedMemberIs(Nel(Username.from_name("john")))
    assert pp.segment.parse("inherited_member:123-456") == InheritedMemberIs(Nel(UserId("123-456")))

    assert pp.segment.parse("name:") == Text("name:")


@pytest.mark.asyncio
async def test_query() -> None:
    assert pp.query.parse("") == UserQuery([])

    q = UserQuery.of(
        S.created(Comparison.is_greater_than, DateTimeCalc(RelativeDate.today, -7, False)),
        S.text("some"),
        S.slug_is("bad slug"),
        S.text("text"),
        S.order(OrderBy(SortableField.score, SortDirection.asc)),
    )
    qstr = 'created>today-7d some slug:"bad slug" text sort:score-asc'
    assert pp.query.parse(qstr) == q
    assert q.render() == qstr

    q = UserQuery(
        [
            S.name_is("al"),
            S.text("hello world hello"),
            S.sort_by((SortableField.score, SortDirection.desc)),
        ]
    )
    qstr = "name:al hello world hello sort:score-desc"
    assert await QueryParser.parse(qstr) == q
    assert q.render() == qstr


@pytest.mark.asyncio
async def test_collapse_member_and_text_query() -> None:
    q = UserQuery.of(
        S.name_is("al"),
        S.text("hello this world"),
        S.direct_member_is(Username.from_name("jane"), Username.from_name("joe")),
    )
    qstr = "name:al hello  direct_member:@jane this world direct_member:@joe"
    assert await QueryParser.parse(qstr) == q
    assert q.render() == "name:al hello this world direct_member:@jane,@joe"


@pytest.mark.asyncio
async def test_restrict_members_query() -> None:
    q = UserQuery.of(
        S.name_is("al"),
        S.text("hello"),
        S.direct_member_is(
            Username.from_name("jane"), Username.from_name("joe"), Username.from_name("jeff"), UserId("123")
        ),
    )
    qstr = "name:al  direct_member:@jane hello direct_member:@joe,@jeff,123,456,@wuff"
    assert (await QueryParser.parse(qstr)) == q


@pytest.mark.asyncio
async def test_invalid_query() -> None:
    result = await QueryParser.parse("type:uu:ue:")
    assert result == UserQuery([Text("type:uu:ue:")])


@pytest.mark.asyncio
async def test_random_query() -> None:
    """Any random string must parse successfully."""
    rlen = random.randint(0, 50)
    rstr = "".join(random.choices(string.printable, k=rlen))
    await QueryParser.parse(rstr)


def test_string_basic() -> None:
    assert pp.string_basic.parse("abcde") == "abcde"
    assert pp.string_basic.parse("project_one") == "project_one"

    with pytest.raises(ParseError):
        pp.string_basic.parse("a b")
    with pytest.raises(ParseError):
        pp.string_basic.parse("a,b")
    with pytest.raises(ParseError):
        pp.string_basic.parse('a"b"')


def test_string_quoted() -> None:
    assert pp.string_quoted.parse('"abc"') == "abc"
    assert pp.string_quoted.parse('"a b c"') == "a b c"
    assert pp.string_quoted.parse('"a,b,c"') == "a,b,c"
    assert pp.string_quoted.parse('"a and \\"b\\" and c"') == 'a and "b" and c'


def test_string_value() -> None:
    assert pp.string_value.parse("abc") == "abc"
    assert pp.string_value.parse('"a b c"') == "a b c"
    assert pp.string_value.parse('"a,b,c"') == "a,b,c"
    assert pp.string_value.parse('"a and \\"b\\" and c"') == 'a and "b" and c'


def test_string_values() -> None:
    assert pp.string_values.parse("a,b") == Nel.of("a", "b")
    assert pp.string_values.parse('a,"b c",d') == Nel.of("a", "b c", "d")


dp = _DateTimeParser()


def test_year() -> None:
    assert dp.year.parse("2022") == 2022
    assert dp.year.parse("1955") == 1955

    with pytest.raises(ParseError):
        dp.year.parse("098")

    with pytest.raises(ParseError):
        dp.year.parse("abc")

    with pytest.raises(ParseError):
        dp.year.parse("80")

    with pytest.raises(ParseError):
        dp.year.parse("8")


def test_month() -> None:
    assert dp.month.parse("1") == 1
    assert dp.month.parse("01") == 1
    assert dp.month.parse("12") == 12
    assert dp.month.parse("8") == 8

    with pytest.raises(ParseError):
        dp.month.parse("0")
    with pytest.raises(ParseError):
        dp.month.parse("-1")
    with pytest.raises(ParseError):
        dp.month.parse("15")
    with pytest.raises(ParseError):
        dp.month.parse("13")


def test_day() -> None:
    assert dp.dom.parse("1") == 1
    assert dp.dom.parse("01") == 1
    assert dp.dom.parse("12") == 12
    assert dp.dom.parse("8") == 8
    assert dp.dom.parse("31") == 31

    with pytest.raises(ParseError):
        dp.dom.parse("0")
    with pytest.raises(ParseError):
        dp.dom.parse("-1")
    with pytest.raises(ParseError):
        dp.dom.parse("32")


def test_hour() -> None:
    assert dp.hour.parse("1") == 1
    assert dp.hour.parse("01") == 1
    assert dp.hour.parse("0") == 0
    assert dp.hour.parse("8") == 8
    assert dp.hour.parse("23") == 23

    with pytest.raises(ParseError):
        dp.hour.parse("24")
    with pytest.raises(ParseError):
        dp.hour.parse("-1")
    with pytest.raises(ParseError):
        dp.hour.parse("abc")


def test_minsec() -> None:
    assert dp.minsec.parse("1") == 1
    assert dp.minsec.parse("01") == 1
    assert dp.minsec.parse("0") == 0
    assert dp.minsec.parse("00") == 0
    assert dp.minsec.parse("8") == 8
    assert dp.minsec.parse("59") == 59

    with pytest.raises(ParseError):
        dp.minsec.parse("60")
    with pytest.raises(ParseError):
        dp.minsec.parse("-1")
    with pytest.raises(ParseError):
        dp.minsec.parse("abc")


def test_partial_date() -> None:
    assert dp.partial_date.parse("2022") == PartialDate(2022)
    assert dp.partial_date.parse("2024-05") == PartialDate(2024, 5, None)

    with pytest.raises(ParseError):
        dp.partial_date.parse("2020-05-01T08:00")
    with pytest.raises(ParseError):
        dp.partial_date.parse("-05-01")
    with pytest.raises(ParseError):
        dp.partial_date.parse("05-01")
    with pytest.raises(ParseError):
        dp.partial_date.parse("2023-15-01")


def test_partial_time() -> None:
    assert dp.partial_time.parse("08:10") == PartialTime(8, 10, None)
    assert dp.partial_time.parse("08") == PartialTime(8)
    assert dp.partial_time.parse("8") == PartialTime(8)
    assert dp.partial_time.parse("8:5") == PartialTime(8, 5, None)
    assert dp.partial_time.parse("08:55:10") == PartialTime(8, 55, 10)

    with pytest.raises(ParseError):
        dp.partial_time.parse("2020-05-01T08:00")
    with pytest.raises(ParseError):
        dp.partial_time.parse("56:56")
    with pytest.raises(ParseError):
        dp.partial_time.parse("000:15")


def test_parital_datetime() -> None:
    assert dp.partial_datetime.parse("2022") == PartialDateTime(PartialDate(2022))
    assert dp.partial_datetime.parse("2024-05") == PartialDateTime(PartialDate(2024, 5, None))
    assert dp.partial_datetime.parse("2024-05T8") == PartialDateTime(PartialDate(2024, 5), PartialTime(8))
    assert dp.partial_datetime.parse("2025-03-01T12Z") == PartialDateTime(
        PartialDate(2025, 3, 1), PartialTime(12), datetime.UTC
    )


def test_relative_date() -> None:
    assert dp.relative_date.parse("today") == RelativeDate.today
    assert dp.relative_date.parse("yesterday") == RelativeDate.yesterday


def test_datetime_calc() -> None:
    assert dp.datetime_calc.parse("2022-05+10d") == DateTimeCalc(PartialDateTime(PartialDate(2022, 5)), 10, False)
    assert dp.datetime_calc.parse("today-5d") == DateTimeCalc(RelativeDate.today, -5, False)
    assert dp.datetime_calc.parse("yesterday/8D") == DateTimeCalc(RelativeDate.yesterday, 8, True)

    with pytest.raises(ParseError):
        dp.datetime_calc.parse("today+-10d")
    with pytest.raises(ParseError):
        dp.datetime_calc.parse("today/-10d")


def test_datetime_ref() -> None:
    assert dp.datetime_ref.parse("2022-05+10d") == DateTimeCalc(PartialDateTime(PartialDate(2022, 5)), 10, False)
    assert dp.datetime_ref.parse("today-5d") == DateTimeCalc(RelativeDate.today, -5, False)
    assert dp.datetime_ref.parse("yesterday/8D") == DateTimeCalc(RelativeDate.yesterday, 8, True)

    assert dp.datetime_ref.parse("today") == RelativeDate.today
    assert dp.datetime_ref.parse("yesterday") == RelativeDate.yesterday

    assert dp.datetime_ref.parse("2022") == PartialDateTime(PartialDate(2022))
    assert dp.datetime_ref.parse("2024-05") == PartialDateTime(PartialDate(2024, 5, None))
    assert dp.datetime_ref.parse("2024-05T8") == PartialDateTime(PartialDate(2024, 5), PartialTime(8))
    assert dp.datetime_ref.parse("2025-03-01T12Z") == PartialDateTime(
        PartialDate(2025, 3, 1), PartialTime(12), datetime.UTC
    )
