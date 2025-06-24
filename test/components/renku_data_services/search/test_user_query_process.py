"""Tests for user query processing."""

from renku_data_services.search.user_query import Segments, SortableField, UserId, Username, UserQuery
from renku_data_services.search.user_query_process import (
    CollapseMembers,
    CollapseText,
    CollectEntityTypes,
    ExtractOrder,
)
from renku_data_services.solr.entity_documents import EntityType
from renku_data_services.solr.solr_client import SortDirection


def test_find_entity_types() -> None:
    q = UserQuery.of(Segments.keyword_is("science"), Segments.name_is("test"))
    assert q.accept(CollectEntityTypes()) is None

    q = UserQuery.of(Segments.keyword_is("science"), Segments.type_is(EntityType.project), Segments.name_is("test"))
    assert q.accept(CollectEntityTypes()) == set([EntityType.project])

    q = UserQuery.of(
        Segments.keyword_is("science"),
        Segments.type_is(EntityType.project, EntityType.dataconnector),
        Segments.name_is("test"),
    )
    assert q.accept(CollectEntityTypes()) == set([EntityType.project, EntityType.dataconnector])

    q = UserQuery.of(
        Segments.keyword_is("science"),
        Segments.type_is(EntityType.project),
        Segments.type_is(EntityType.dataconnector),
        Segments.name_is("test"),
    )
    assert q.accept(CollectEntityTypes()) == set()


def test_query_extract_order() -> None:
    q = UserQuery.of(Segments.name_is("test"), Segments.text("some"), Segments.keyword_is("datascience"))
    assert q.accept(ExtractOrder()) == (
        [Segments.name_is("test"), Segments.text("some"), Segments.keyword_is("datascience")],
        None,
    )

    q = UserQuery.of(
        Segments.name_is("test"),
        Segments.text("some"),
        Segments.keyword_is("datascience"),
        Segments.sort_by((SortableField.score, SortDirection.asc)),
    )
    assert q.accept(ExtractOrder()) == (
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
    assert q.accept(ExtractOrder()) == (
        [Segments.name_is("test"), Segments.text("some"), Segments.keyword_is("datascience")],
        Segments.sort_by((SortableField.fname, SortDirection.desc), (SortableField.score, SortDirection.asc)),
    )


def test_collapse_text_segments() -> None:
    q = UserQuery.of(
        Segments.name_is("john"),
        Segments.text("hello"),
        Segments.text("world"),
        Segments.keyword_is("check"),
        Segments.text("help"),
    )
    assert q.accept(CollapseText()) == UserQuery.of(
        Segments.name_is("john"),
        Segments.text("hello world"),
        Segments.keyword_is("check"),
        Segments.text("help"),
    )


def test_restrict_members_query() -> None:
    q = UserQuery.of(
        Segments.name_is("al"),
        Segments.member_is(Username.from_name("jane")),
        Segments.text("hello"),
        Segments.member_is(
            Username.from_name("joe"),
            Username.from_name("jeff"),
            UserId("123"),
            UserId("456"),
            Username.from_name("wuff"),
        ),
    )
    assert q.transform(CollapseMembers()) == UserQuery.of(
        Segments.name_is("al"),
        Segments.text("hello"),
        Segments.member_is(
            Username.from_name("jane"), Username.from_name("joe"), Username.from_name("jeff"), UserId("123")
        ),
    )
