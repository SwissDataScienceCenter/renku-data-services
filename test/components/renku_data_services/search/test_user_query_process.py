"""Tests for user query processing."""

import pytest

from renku_data_services.search.user_query import Segments as S
from renku_data_services.search.user_query import UserId, Username, UserQuery
from renku_data_services.search.user_query_process import (
    CollapseMembers,
    CollapseText,
    CollectEntityTypes,
)
from renku_data_services.solr.entity_documents import EntityType


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
