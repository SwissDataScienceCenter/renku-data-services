"""A small abstraction for creating queries for solr."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Self

import renku_data_services.search.solr_token as st
from renku_data_services.search.solr_token import SolrToken
from renku_data_services.search.user_query import (
    Comparison,
    Created,
    CreatedByIs,
    FieldTerm,
    IdIs,
    KeywordIs,
    NameIs,
    NamespaceIs,
    OrderBy,
    Query,
    RoleIs,
    SlugIs,
    SortableField,
    Text,
    TypeIs,
    VisibilityIs,
)
from renku_data_services.solr.entity_schema import Fields
from renku_data_services.solr.solr_client import SortDirection
from renku_data_services.solr.solr_schema import FieldName


@dataclass
class SolrUserQuery:
    """A solr query with an optional sort definition."""

    query: SolrToken
    sort: list[tuple[FieldName, SortDirection]]

    def append(self, next: Self) -> Self:
        """Creates a new query appending `next` to this."""
        return type(self)(SolrToken(f"{self.query} AND {next.query}"), self.sort + next.sort)

    def query_str(self) -> str:
        """Return the solr query string."""
        if self.query == "":
            return st.all_entity_types()
        else:
            return self.query


@dataclass
class AdminRole:
    """An admin is searching."""

    id: str


@dataclass
class UserRole:
    """A logged in user is searching."""

    id: str


type SearchRole = AdminRole | UserRole


@dataclass
class Context:
    """Contextual information available at search time that can be used to create the query."""

    current_time: datetime
    zone: tzinfo
    role: SearchRole | None


class QueryInterpreter(ABC):
    """Interpreter for user search queries."""

    @abstractmethod
    def run(self, ctx: Context, q: Query) -> SolrUserQuery:
        """Convert a user query into a search query."""
        ...

    @classmethod
    def default(cls) -> "QueryInterpreter":
        """Return the default query interpreter."""
        return LuceneQueryInterpreter()


class LuceneQueryInterpreter(QueryInterpreter):
    """Convert a user search query into solrs standard query.

    See https://solr.apache.org/guide/solr/latest/query-guide/standard-query-parser.html

    This class takes care of converting a user supplied query into
    something that solr can use. It is not yet the final query,
    constraints and other parts are added. This is only solr
    translation for the user search query part.

    Here the search query can be tweaked if necessary (fuzzy searching
    etc).
    """

    def _to_solr_sort(self, ob: OrderBy) -> tuple[FieldName, SortDirection]:
        match ob.field:
            case SortableField.fname:
                return (Fields.name, ob.direction)
            case SortableField.score:
                return (Fields.score, ob.direction)
            case SortableField.created:
                return (Fields.creation_date, ob.direction)

    def _from_term(self, ctx: Context, term: FieldTerm) -> SolrToken:
        match term:
            case TypeIs() as t:
                return st.field_is_any(Fields.entity_type, t.values.map(st.from_entity_type))
            case IdIs() as t:
                return st.field_is_any(Fields.id, t.values.map(st.from_str))
            case NameIs() as t:
                return st.field_is_any(Fields.name, t.values.map(st.from_str))
            case SlugIs() as t:
                return st.field_is_any(Fields.slug, t.values.map(st.from_str))
            case VisibilityIs() as t:
                return st.field_is_any(Fields.visibility, t.values.map(st.from_visibility))
            case KeywordIs() as t:
                return st.field_is_any(Fields.keywords, t.values.map(st.from_str))
            case NamespaceIs() as t:
                return st.field_is_any(Fields.namespace, t.values.map(st.from_str))
            case CreatedByIs() as t:
                return st.field_is_any(Fields.created_by, t.values.map(st.from_str))
            case RoleIs() as t:
                raise Exception("not implemented")
            case Created() as t:
                tokens: list[SolrToken] = []
                match t.cmp:
                    case Comparison.is_equal:
                        for dt in t.values.to_list():
                            (min, max_opt) = dt.resolve(ctx.current_time, ctx.zone)
                            tokens.append(st.created_range(min, max_opt) if max_opt is not None else st.created_is(min))

                        return st.fold_or(tokens)

                    case Comparison.is_greater_than:
                        for dt in t.values.to_list():
                            (min, max_opt) = dt.resolve(ctx.current_time, ctx.zone)
                            tokens.append(st.created_gt(max_opt or min))

                        return st.fold_or(tokens)

                    case Comparison.is_lower_than:
                        for dt in t.values.to_list():
                            (min, _) = dt.resolve(ctx.current_time, ctx.zone)
                            tokens.append(st.created_lt(min))

                        return st.fold_or(tokens)

    def _from_text(self, text: Text) -> SolrToken:
        return st.content_all(text.value)

    def _from_segment(self, ctx: Context, segment: FieldTerm | Text) -> SolrToken:
        match segment:
            case Text() as t:
                return self._from_text(t)
            case t:
                return self._from_term(ctx, t)

    def run(self, ctx: Context, q: Query) -> SolrUserQuery:
        """Convert a user query into a search query."""
        (terms, sort) = q.extract_order()
        sort = sort.fields.to_list() if sort is not None else []

        solr_sort = [self._to_solr_sort(e) for e in sort]
        solr_token = [self._from_segment(ctx, e) for e in terms]
        return SolrUserQuery(st.fold_and(solr_token), solr_sort)
