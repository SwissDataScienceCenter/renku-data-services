"""Tests for the query parser."""

from parsy import ParseError
import pytest
from renku_data_services.search.user_query import Comparison, Nel, OrderBy, SortableField, TypeIs
from renku_data_services.search.user_query_parser import ParsePrimitives
from renku_data_services.solr.entity_documents import EntityType
from renku_data_services.solr.solr_client import SortDirection


pp = ParsePrimitives()


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
            value = OrderBy(sf, dir)
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
