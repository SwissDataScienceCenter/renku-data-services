"""Tests for user query processing."""

import pytest

from renku_data_services.search.user_query import Segments as S
from renku_data_services.search.user_query import SortableField, UserId, Username, UserQuery
from renku_data_services.search.user_query_process import (
    CollapseMembers,
    CollapseText,
    CollectEntityTypes,
    ExtractOrder,
)
from renku_data_services.solr.entity_documents import EntityType
from renku_data_services.solr.solr_client import SortDirection


@pytest.mark.asyncio
async def test_find_entity_types() -> None:
    q = UserQuery.of(S.keyword_is("science"), S.name_is("test"))
    assert await q.accept(CollectEntityTypes()) is None

    q = UserQuery.of(S.keyword_is("science"), S.type_is(EntityType.project), S.name_is("test"))
    assert await q.accept(CollectEntityTypes()) == set([EntityType.project])

    q = UserQuery.of(
        S.keyword_is("science"),
        S.type_is(EntityType.project, EntityType.dataconnector),
        S.name_is("test"),
    )
    assert await q.accept(CollectEntityTypes()) == set([EntityType.project, EntityType.dataconnector])

    q = UserQuery.of(
        S.keyword_is("science"),
        S.type_is(EntityType.project),
        S.type_is(EntityType.dataconnector),
        S.name_is("test"),
    )
    assert await q.accept(CollectEntityTypes()) == set()


@pytest.mark.asyncio
async def test_query_extract_order() -> None:
    q = UserQuery.of(S.name_is("test"), S.text("some"), S.keyword_is("datascience"))
    assert await q.accept(ExtractOrder()) == (
        [S.name_is("test"), S.text("some"), S.keyword_is("datascience")],
        None,
    )

    q = UserQuery.of(
        S.name_is("test"),
        S.text("some"),
        S.keyword_is("datascience"),
        S.sort_by((SortableField.score, SortDirection.asc)),
    )
    assert await q.accept(ExtractOrder()) == (
        [S.name_is("test"), S.text("some"), S.keyword_is("datascience")],
        S.sort_by((SortableField.score, SortDirection.asc)),
    )

    q = UserQuery.of(
        S.name_is("test"),
        S.sort_by((SortableField.fname, SortDirection.desc)),
        S.text("some"),
        S.keyword_is("datascience"),
        S.sort_by((SortableField.score, SortDirection.asc)),
    )
    assert await q.accept(ExtractOrder()) == (
        [S.name_is("test"), S.text("some"), S.keyword_is("datascience")],
        S.sort_by((SortableField.fname, SortDirection.desc), (SortableField.score, SortDirection.asc)),
    )


@pytest.mark.asyncio
async def test_collapse_text_segments() -> None:
    q = UserQuery.of(
        S.name_is("john"),
        S.text("hello"),
        S.text("world"),
        S.keyword_is("check"),
        S.text("help"),
    )
    assert await q.accept(CollapseText()) == UserQuery.of(
        S.name_is("john"),
        S.text("hello world"),
        S.keyword_is("check"),
        S.text("help"),
    )


@pytest.mark.asyncio
async def test_restrict_members_query() -> None:
    q = UserQuery.of(
        S.name_is("al"),
        S.direct_member_is(Username.from_name("jane")),
        S.text("hello"),
        S.direct_member_is(
            Username.from_name("joe"),
            Username.from_name("jeff"),
            UserId("123"),
            UserId("456"),
            Username.from_name("wuff"),
        ),
    )
    assert await q.transform(CollapseMembers()) == UserQuery.of(
        S.name_is("al"),
        S.text("hello"),
        S.direct_member_is(
            Username.from_name("jane"), Username.from_name("joe"), Username.from_name("jeff"), UserId("123")
        ),
    )
