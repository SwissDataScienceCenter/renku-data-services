"""Tests for user query."""

from datetime import UTC, datetime, timedelta

from ulid import ULID

from renku_data_services.search.user_query import (
    DateTimeCalc,
    Helper,
    IdIs,
    Nel,
    Order,
    OrderBy,
    PartialDate,
    PartialDateTime,
    PartialTime,
    RelativeDate,
    Segments,
    SortableField,
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


def test_nel() -> None:
    value = Nel(1)
    assert value.to_list() == [1]

    value = Nel(1, [2, 3])
    assert value.to_list() == [1, 2, 3]

    # sad, mypy doesn't catch this
    value = Nel.of(1, 2, 3, "a")
    assert value.to_list() == [1, 2, 3, "a"]

    value = Nel.of(1, 2, 3, 4)
    assert value.to_list() == [1, 2, 3, 4]

    value = Nel.of(1, 2).append(Nel.of(3, 4))
    assert value.to_list() == [1, 2, 3, 4]

    nel = Nel.of(1, 2)
    value = nel.append_list([])
    assert value is nel

    value = nel.append_list([3, 4])
    assert value.to_list() == [1, 2, 3, 4]

    nel = Nel.from_list([])
    assert nel is None

    nel = Nel.from_list([1, 2, 3])
    assert nel == Nel.of(1, 2, 3)


def test_helper_quote() -> None:
    assert Helper.quote("hello world") == '"hello world"'
    assert Helper.quote("hello ") == '"hello "'
    assert Helper.quote("1,2") == '"1,2"'
    assert Helper.quote('x="3"') == '"x="3""'


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
    assert str(PartialDate(2025, 2).max()) == "2025-02-28"
    assert str(PartialDate(2024, 2).max()) == "2024-02-29"
    assert str(PartialDate(2025, 2).min()) == "2025-02-01"
    assert str(PartialDate(2021).max()) == "2021-12-31"
    assert str(PartialDate(2021).min()) == "2021-01-01"
    assert str(PartialDate(2025, 3, 7).max()) == "2025-03-07"
    assert str(PartialDate(2025, 3, 7).min()) == "2025-03-07"


def test_partial_time_render() -> None:
    assert PartialTime(12).render() == "12"
    assert PartialTime(12, 30).render() == "12:30"
    assert PartialTime(12, 30, 15).render() == "12:30:15"


def test_partial_time_min_max() -> None:
    assert str(PartialTime(12).max()) == "12:59:59"
    assert str(PartialTime(12).min()) == "12:00:00"
    assert str(PartialTime(2, 30).max()) == "02:30:59"
    assert str(PartialTime(2, 30).min()) == "02:30:00"
    assert str(PartialTime(12, 30, 15).max()) == "12:30:15"
    assert str(PartialTime(12, 30, 15).min()) == "12:30:15"


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


def test_query_extract_order() -> None:
    q = UserQuery.of(Segments.name_is("test"), Segments.text("some"), Segments.keyword_is("datascience"))
    assert q.extract_order() == (
        [Segments.name_is("test"), Segments.text("some"), Segments.keyword_is("datascience")],
        None,
    )

    q = UserQuery.of(
        Segments.name_is("test"),
        Segments.text("some"),
        Segments.keyword_is("datascience"),
        Segments.sort_by((SortableField.score, SortDirection.asc)),
    )
    assert q.extract_order() == (
        [Segments.name_is("test"), Segments.text("some"), Segments.keyword_is("datascience")],
        Segments.sort_by((SortableField.score, SortDirection.asc)),
    )

    q = UserQuery.of(
        Segments.name_is("test"),
        Segments.sort_by((SortableField.fname, SortDirection.desc)),
        Segments.text("some"),
        Segments.keyword_is("datascience"),
        Segments.sort_by((SortableField.score, SortDirection.asc)),
    )
    assert q.extract_order() == (
        [Segments.name_is("test"), Segments.text("some"), Segments.keyword_is("datascience")],
        Segments.sort_by((SortableField.fname, SortDirection.desc), (SortableField.score, SortDirection.asc)),
    )
