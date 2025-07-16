"""Tests for user query."""

from datetime import UTC, datetime, timedelta

import pytest
from ulid import ULID

from renku_data_services.base_models.nel import Nel
from renku_data_services.search.user_query import (
    DateTimeCalc,
    EmptyUserQueryVisitor,
    FieldTerm,
    Helper,
    IdIs,
    Order,
    OrderBy,
    PartialDate,
    PartialDateTime,
    PartialTime,
    RelativeDate,
    Segment,
    Segments,
    SortableField,
    Text,
    TypeIs,
    UserQuery,
)
from renku_data_services.solr.entity_documents import EntityType
from renku_data_services.solr.solr_client import SortDirection

ref_date: datetime = datetime(2024, 2, 27, 15, 34, 55, tzinfo=UTC)


def midnight(d: datetime) -> datetime:
    return d.replace(hour=0, minute=0, second=0, microsecond=0)


def end_of_day(d: datetime) -> datetime:
    return d.replace(hour=23, minute=59, second=59, microsecond=0)


def test_render_keywords() -> None:
    assert Segments.keyword_is("hello").render() == "keyword:hello"
    assert Segments.keyword_is("hello-me").render() == "keyword:hello-me"
    assert Segments.keyword_is("hello me").render() == 'keyword:"hello me"'
    assert Segments.keyword_is("tl,dr", "data").render() == 'keyword:"tl,dr",data'
    assert Segments.keyword_is("""a "and" b""", "data").render() == 'keyword:"a \\"and\\" b",data'


def test_render_order_by() -> None:
    order = OrderBy(SortableField.fname, SortDirection.asc)
    assert order.render() == "name-asc"


def test_render_order() -> None:
    order = Order(Nel(OrderBy(SortableField.fname, SortDirection.asc)))
    assert order.render() == "sort:name-asc"

    order = Order(
        Nel.of(OrderBy(SortableField.fname, SortDirection.asc), OrderBy(SortableField.score, SortDirection.desc)),
    )
    assert order.render() == "sort:name-asc,score-desc"


def test_helper_quote() -> None:
    assert Helper.quote("hello world") == '"hello world"'
    assert Helper.quote("hello ") == '"hello "'
    assert Helper.quote("1,2") == '"1,2"'
    assert Helper.quote('x="3"') == '"x=\\"3\\""'
    assert Helper.quote("""a "and" b""") == '"a \\"and\\" b"'


def test_type_is() -> None:
    ft = TypeIs(Nel.of(EntityType.project))
    assert ft.render() == "type:Project"

    ft = TypeIs(Nel.of(EntityType.project, EntityType.group))
    assert ft.render() == "type:Project,Group"


def test_id_is() -> None:
    ft = IdIs(Nel.of("a b c"))
    assert ft.render() == 'id:"a b c"'

    id = ULID()
    ft = IdIs(Nel.of(str(id)))
    assert ft.render() == f"id:{id}"


def test_free_text() -> None:
    assert Segments.text("abc").render() == "abc"
    assert Segments.text("abc abc").render() == "abc abc"


def test_partial_date_render() -> None:
    assert PartialDate(2025, 2).render() == "2025-02"
    assert PartialDate(2021).render() == "2021"
    assert PartialDate(2025, 3, 7).render() == "2025-03-07"


def test_partial_date_min_max() -> None:
    assert str(PartialDate(2025, 2).date_max()) == "2025-02-28"
    assert str(PartialDate(2024, 2).date_max()) == "2024-02-29"
    assert str(PartialDate(2025, 2).date_min()) == "2025-02-01"
    assert str(PartialDate(2021).date_max()) == "2021-12-31"
    assert str(PartialDate(2021).date_min()) == "2021-01-01"
    assert str(PartialDate(2025, 3, 7).date_max()) == "2025-03-07"
    assert str(PartialDate(2025, 3, 7).date_min()) == "2025-03-07"


def test_partial_time_render() -> None:
    assert PartialTime(12).render() == "12"
    assert PartialTime(12, 30).render() == "12:30"
    assert PartialTime(12, 30, 15).render() == "12:30:15"


def test_partial_time_min_max() -> None:
    assert str(PartialTime(12).time_max()) == "12:59:59"
    assert str(PartialTime(12).time_min()) == "12:00:00"
    assert str(PartialTime(2, 30).time_max()) == "02:30:59"
    assert str(PartialTime(2, 30).time_min()) == "02:30:00"
    assert str(PartialTime(12, 30, 15).time_max()) == "12:30:15"
    assert str(PartialTime(12, 30, 15).time_min()) == "12:30:15"


def test_partial_datetime_render() -> None:
    assert PartialDateTime(PartialDate(2022)).render() == "2022"
    assert PartialDateTime(PartialDate(2022), PartialTime(8)).render() == "2022T08"


def test_relative_date() -> None:
    assert RelativeDate.today.render() == "today"
    assert RelativeDate.yesterday.render() == "yesterday"


def test_datetime_calc() -> None:
    d = DateTimeCalc(PartialDateTime(PartialDate(2022)), 5, False)
    assert d.render() == "2022+5d"

    d = DateTimeCalc(PartialDateTime(PartialDate(2022), PartialTime(8)), 5, False)
    assert d.render() == "2022T08+5d"

    d = DateTimeCalc(PartialDateTime(PartialDate(2022, 5)), -5, False)
    assert d.render() == "2022-05-5d"

    d = DateTimeCalc(RelativeDate.today, -7, False)
    assert d.render() == "today-7d"

    d = DateTimeCalc(RelativeDate.yesterday, 7, False)
    assert d.render() == "yesterday+7d"


def test_resolve_relative_date() -> None:
    assert RelativeDate.today.resolve(ref_date, UTC) == (midnight(ref_date), end_of_day(ref_date))
    assert RelativeDate.yesterday.resolve(ref_date, UTC) == (
        midnight(ref_date) - timedelta(days=1),
        end_of_day(ref_date) - timedelta(days=1),
    )


def test_resolve_partial_date() -> None:
    pd = PartialDateTime(PartialDate(2023, 5))
    assert pd.resolve(ref_date, UTC) == (pd.datetime_min(UTC), pd.datetime_max(UTC))

    pd = PartialDateTime(PartialDate(2023, 5, 1), PartialTime(15, 22, 15))
    assert pd.resolve(ref_date, UTC) == (pd.datetime_max(UTC), None)


def test_resolve_date_calc() -> None:
    pd = PartialDateTime(PartialDate(2023, 5))
    calc = DateTimeCalc(pd, 5, False)
    assert calc.resolve(ref_date, UTC) == (pd.datetime_min(UTC) + timedelta(days=5), None)

    calc = DateTimeCalc(pd, -5, False)
    assert calc.resolve(ref_date, UTC) == (pd.datetime_min(UTC) - timedelta(days=5), None)

    calc = DateTimeCalc(pd, 5, True)
    assert calc.resolve(ref_date, UTC) == (
        pd.datetime_min(UTC) - timedelta(days=5),
        pd.datetime_max(UTC) + timedelta(days=5),
    )


class TestUserQueryTransform(EmptyUserQueryVisitor[UserQuery]):
    def __init__(self, to_add: Segment) -> None:
        self.segments: list[Segment] = []
        self.to_add = to_add

    async def visit_field_term(self, ft: FieldTerm) -> None:
        self.segments.append(ft)

    async def visit_order(self, order: Order) -> None:
        self.segments.append(order)

    async def visit_text(self, text: Text) -> None:
        self.segments.append(text)

    async def build(self) -> UserQuery:
        self.segments.append(self.to_add)
        return UserQuery(self.segments)


@pytest.mark.asyncio
async def test_transform() -> None:
    q0 = UserQuery.of(Segments.name_is("john"), Segments.text("help"))
    q = await q0.transform(
        TestUserQueryTransform(Segments.type_is(EntityType.project)), TestUserQueryTransform(Segments.id_is("id-123"))
    )

    assert q == UserQuery(q0.segments + [Segments.type_is(EntityType.project), Segments.id_is("id-123")])
