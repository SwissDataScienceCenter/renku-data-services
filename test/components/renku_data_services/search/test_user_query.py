"""Tests for user query."""

from ulid import ULID

from renku_data_services.search.user_query import Helper, IdIs, Nel, Order, OrderBy, SortableField, TypeIs
from renku_data_services.solr.entity_documents import EntityType
from renku_data_services.solr.solr_client import SortDirection


def test_render_order() -> None:
    order = Order(field=OrderBy(SortableField.fname, SortDirection.asc))
    assert order.render() == "name-asc"

    order = Order(
        field=OrderBy(SortableField.fname, SortDirection.asc),
        more_fields=[OrderBy(SortableField.score, SortDirection.desc)],
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
