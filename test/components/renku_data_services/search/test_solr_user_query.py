"""Tests for the solr_user_query module."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

import renku_data_services.search.solr_token as st
from renku_data_services.authz.models import Role, Visibility
from renku_data_services.search.solr_user_query import AuthAccess, Context, SolrUserQuery
from renku_data_services.search.solr_user_query import LuceneQueryInterpreter as L
from renku_data_services.search.user_query import (
    Created,
    CreatedByIs,
    DateTimeCalc,
    IdIs,
    KeywordIs,
    NameIs,
    NamespaceIs,
    Nel,
    OrderBy,
    PartialDate,
    PartialDateTime,
    RelativeDate,
    RoleIs,
    Segments,
    SlugIs,
    SortableField,
    Text,
    TypeIs,
    UserQuery,
    VisibilityIs,
)
from renku_data_services.solr.entity_documents import EntityType
from renku_data_services.solr.entity_schema import Fields
from renku_data_services.solr.solr_client import SortDirection

ref_date: datetime = datetime(2024, 2, 27, 15, 34, 55, tzinfo=UTC)
ctx: Context = Context.for_anonymous(ref_date, UTC)


@dataclass
class TestAuthAccess(AuthAccess):
    result: list[str]

    async def get_role_ids(self, user_id: str, roles: Nel[Role]) -> list[str]:
        return self.result

    @classmethod
    def of(cls, *args: str) -> AuthAccess:
        return TestAuthAccess(list(args))


def midnight(d: datetime) -> datetime:
    return d.replace(hour=0, minute=0, second=0, microsecond=0)


def end_of_day(d: datetime) -> datetime:
    return d.replace(hour=23, minute=59, second=59, microsecond=0)


def test_to_solr_sort() -> None:
    assert L._to_solr_sort(OrderBy(field=SortableField.fname, direction=SortDirection.asc)) == (
        Fields.name,
        SortDirection.asc,
    )


@pytest.mark.asyncio
async def test_from_term() -> None:
    assert await L._from_term(ctx, TypeIs(Nel.of(EntityType.project))) == st.field_is_any(
        Fields.entity_type, Nel.of(st.from_entity_type(EntityType.project))
    )
    assert await L._from_term(ctx, IdIs(Nel.of("id1"))) == st.field_is_any(Fields.id, Nel.of(st.from_str("id1")))
    assert await L._from_term(ctx, NameIs(Nel.of("Tadej"))) == st.field_is_any(
        Fields.name, Nel.of(st.from_str("Tadej"))
    )
    assert await L._from_term(ctx, SlugIs(Nel.of("a/b"))) == st.field_is_any(Fields.slug, Nel.of(st.from_str("a/b")))
    assert await L._from_term(ctx, VisibilityIs(Nel.of(Visibility.PUBLIC))) == st.field_is_any(
        Fields.visibility, Nel.of(st.from_visibility(Visibility.PUBLIC))
    )
    assert await L._from_term(ctx, KeywordIs(Nel.of("k1", "w2"))) == st.field_is_any(
        Fields.keywords, Nel.of(st.from_str("k1"), st.from_str("w2"))
    )
    assert await L._from_term(ctx, NamespaceIs(Nel.of("ns12"))) == st.field_is_any(
        Fields.namespace, Nel.of(st.from_str("ns12"))
    )
    assert await L._from_term(ctx, CreatedByIs(Nel.of("12-34"))) == st.field_is_any(
        Fields.created_by, Nel.of(st.from_str("12-34"))
    )

    assert await L._from_term(ctx, RoleIs(Nel.of(Role.OWNER))) == st.empty()
    assert await L._from_term(
        ctx.with_user_role("user1").with_auth_access(TestAuthAccess.of("id1", "id2")), RoleIs(Nel.of(Role.OWNER))
    ) == st.id_in(Nel.of("id1", "id2"))
    assert await L._from_term(
        ctx.with_admin_role("user1").with_auth_access(TestAuthAccess.of("id1", "id2")), RoleIs(Nel.of(Role.OWNER))
    ) == st.id_in(Nel.of("id1", "id2"))


@pytest.mark.asyncio
async def test_from_term_date() -> None:
    assert await L._from_term(ctx, Created.eq(PartialDateTime(PartialDate(2024)))) == st.created_range(
        datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 12, 31, 23, 59, 59, tzinfo=UTC)
    )
    assert await L._from_term(ctx, Created.eq(PartialDateTime(PartialDate(2023, 8, 1)))) == st.created_range(
        datetime(2023, 8, 1, tzinfo=UTC), datetime(2023, 8, 1, 23, 59, 59, tzinfo=UTC)
    )
    assert await L._from_term(ctx, Created.eq(RelativeDate.today)) == st.created_range(
        midnight(ref_date), end_of_day(ref_date)
    )

    assert await L._from_term(ctx, Created.lt(PartialDateTime(PartialDate(2024)))) == st.created_lt(
        datetime(2024, 1, 1, tzinfo=UTC)
    )
    assert await L._from_term(ctx, Created.gt(PartialDateTime(PartialDate(2024)))) == st.created_gt(
        datetime(2024, 12, 31, 23, 59, 59, tzinfo=UTC)
    )
    assert await L._from_term(ctx, Created.eq(DateTimeCalc(RelativeDate.today, 2, True))) == st.created_range(
        midnight(ref_date - timedelta(days=2)), end_of_day(ref_date + timedelta(days=2))
    )
    assert await L._from_term(ctx, Created.gt(DateTimeCalc(RelativeDate.today, -7, False))) == st.created_gt(
        midnight(ref_date - timedelta(days=7))
    )


def test_from_text() -> None:
    assert L._from_text(Text("blah")) == st.content_all("blah")
    assert L._from_text(Text("blah blah")) == st.content_all("blah blah")


@pytest.mark.asyncio
async def test_from_segment() -> None:
    assert await L._from_segment(ctx, Text("blah")) == st.content_all("blah")
    assert await L._from_segment(ctx, Created.gt(DateTimeCalc(RelativeDate.today, -7, False))) == st.created_gt(
        midnight(ref_date - timedelta(days=7))
    )
    assert await L._from_segment(ctx, Created.eq(RelativeDate.today)) == st.created_range(
        midnight(ref_date), end_of_day(ref_date)
    )
    assert await L._from_segment(ctx, IdIs(Nel.of("id1"))) == st.field_is_any(Fields.id, Nel.of(st.from_str("id1")))
    assert await L._from_segment(ctx, NameIs(Nel.of("Tadej"))) == st.field_is_any(
        Fields.name, Nel.of(st.from_str("Tadej"))
    )


@pytest.mark.asyncio
async def test_interpreter_run() -> None:
    ll = L()
    assert await ll.run(ctx, UserQuery.of()) == SolrUserQuery(st.empty(), [])
    assert await ll.run(ctx, UserQuery.of(Segments.keyword_is("data"), Segments.text("blah"))) == SolrUserQuery(
        st.fold_and([st.field_is(Fields.keywords, st.from_str("data")), st.content_all("blah")]), []
    )
    assert await ll.run(
        ctx,
        UserQuery.of(
            Segments.keyword_is("data"),
            Segments.text("blah"),
            Segments.sort_by((SortableField.score, SortDirection.desc)),
        ),
    ) == SolrUserQuery(
        st.fold_and([st.field_is(Fields.keywords, st.from_str("data")), st.content_all("blah")]),
        [(Fields.score, SortDirection.desc)],
    )


@pytest.mark.asyncio
async def test_interpreter_run_remove_empty() -> None:
    ll = L()
    assert await ll.run(
        ctx, UserQuery.of(Segments.id_is("id1"), Segments.role_is(Role.OWNER), Segments.id_is("id2"))
    ) == SolrUserQuery(st.SolrToken("id:id1 AND id:id2"), [])
