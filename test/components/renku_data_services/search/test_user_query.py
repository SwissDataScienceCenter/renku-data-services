"""Tests for user query."""

from ulid import ULID

from renku_data_services.search.user_query import Helper, IdIs, Nel, Order, OrderBy, PartialDate, PartialDateTime, PartialTime, SortableField, TypeIs
from renku_data_services.solr.entity_documents import EntityType
from renku_data_services.solr.solr_client import SortDirection


def test_render_order() -> None:
    order = Order(Nel(OrderBy(SortableField.fname, SortDirection.asc)))
    assert order.render() == "name-asc"

    order = Order(
        Nel.of(OrderBy(SortableField.fname, SortDirection.asc), OrderBy(SortableField.score, SortDirection.desc)),
    )
    assert order.render() == "name-asc,score-desc"


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
