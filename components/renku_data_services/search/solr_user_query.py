"""Creating querios for solr given a parsed user search query."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, tzinfo

import renku_data_services.search.solr_token as st
from renku_data_services.authz.models import Role
from renku_data_services.base_models.core import APIUser
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
    Nel,
    OrderBy,
    RoleIs,
    SlugIs,
    SortableField,
    Text,
    TypeIs,
    UserQuery,
    VisibilityIs,
)
from renku_data_services.solr.entity_schema import Fields
from renku_data_services.solr.solr_client import SortDirection
from renku_data_services.solr.solr_schema import FieldName


@dataclass
class SolrUserQuery:
    """A solr query with an optional sort definition.

    This is the result of interpreting a user search query.
    """

    query: SolrToken
    sort: list[tuple[FieldName, SortDirection]]

    def append(self, next: SolrUserQuery) -> SolrUserQuery:
        """Creates a new query appending `next` to this."""
        return type(self)(SolrToken(f"({self.query}) AND ({next.query})"), self.sort + next.sort)

    def query_str(self) -> str:
        """Return the solr query string."""
        if self.query == "":
            return st.all_entities()
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


class AuthAccess(ABC):
    """Access authorization information."""

    @abstractmethod
    async def get_role_ids(self, user_id: str, roles: Nel[Role]) -> list[str]:
        """Return resource ids for which the given user has the given role."""
        ...

    @classmethod
    def none(cls) -> AuthAccess:
        """An implementation returning no access."""
        return _NoAuthAccess()


class _NoAuthAccess(AuthAccess):
    async def get_role_ids(self, user_id: str, roles: Nel[Role]) -> list[str]:
        return []


@dataclass
class Context:
    """Contextual information available at search time that can be used to create the query."""

    current_time: datetime
    zone: tzinfo
    role: SearchRole | None
    auth_access: AuthAccess = field(default_factory=AuthAccess.none)

    def with_role(self, role: SearchRole) -> Context:
        """Return a copy wit the given role set."""
        return self if self.role == role else Context(self.current_time, self.zone, role)

    def with_user_role(self, user_id: str) -> Context:
        """Return a copy with the given user id as user role set."""
        return self if self.role == UserRole(user_id) else Context(self.current_time, self.zone, UserRole(user_id))

    def with_admin_role(self, user_id: str) -> Context:
        """Return a copy with the given user id as admin role set."""
        return self if self.role == AdminRole(user_id) else Context(self.current_time, self.zone, AdminRole(user_id))

    def with_anonymous(self) -> Context:
        """Return a copy with no search role set."""
        return self if self.role is None else Context(self.current_time, self.zone, None)

    def with_api_user(self, api_user: APIUser) -> Context:
        """Return a copy with the search role set by the APIUser."""
        if api_user.id is not None and api_user.is_admin:
            return self.with_admin_role(api_user.id)
        elif api_user.id is not None and api_user.is_authenticated:
            return self.with_user_role(api_user.id)
        else:
            return self.with_anonymous()

    def with_auth_access(self, aa: AuthAccess) -> Context:
        """Return a copy with the given AuthAccess set."""
        return Context(self.current_time, self.zone, self.role, aa)

    async def get_ids_for_roles(self, roles: Nel[Role]) -> list[str] | None:
        """Return a list of ids the user has one of the given roles.

        Return None when anonymous.
        """
        match self.role:
            case UserRole() as r:
                return await self.auth_access.get_role_ids(r.id, roles)
            case AdminRole() as r:
                return await self.auth_access.get_role_ids(r.id, roles)
            case _:
                return None

    @classmethod
    def for_anonymous(cls, current_time: datetime, zone: tzinfo) -> Context:
        """Creates a Context for interpreting a query as anonymous user."""
        return Context(current_time, zone, None)

    @classmethod
    def for_admin(cls, current_time: datetime, zone: tzinfo, user_id: str) -> Context:
        """Creates a Context for interpreting a query as an admin."""
        return Context(current_time, zone, AdminRole(user_id))

    @classmethod
    def for_user(cls, current_time: datetime, zone: tzinfo, user_id: str) -> Context:
        """Creates a Context for interpreting a query as a normal user."""
        return Context(current_time, zone, UserRole(user_id))

    @classmethod
    def for_api_user(cls, current_time: datetime, zone: tzinfo, api_user: APIUser) -> Context:
        """Creates a Context for the give APIUser."""
        return cls.for_anonymous(current_time, zone).with_api_user(api_user)


class QueryInterpreter(ABC):
    """Interpreter for user search queries."""

    @abstractmethod
    async def run(self, ctx: Context, q: UserQuery) -> SolrUserQuery:
        """Convert a user query into a search query."""
        ...

    @classmethod
    def default(cls) -> QueryInterpreter:
        """Return the default query interpreter."""
        return LuceneQueryInterpreter()


class LuceneQueryInterpreter(QueryInterpreter):
    """Convert a user search query into solrs standard query.

    See https://solr.apache.org/guide/solr/latest/query-guide/standard-query-parser.html

    This class takes care of converting a user supplied query into the
    corresponding solr query.

    Here the search query can be tweaked if necessary (fuzzy searching
    etc).

    """

    @classmethod
    def _to_solr_sort(cls, ob: OrderBy) -> tuple[FieldName, SortDirection]:
        match ob.field:
            case SortableField.fname:
                return (Fields.name, ob.direction)
            case SortableField.score:
                return (Fields.score, ob.direction)
            case SortableField.created:
                return (Fields.creation_date, ob.direction)

    @classmethod
    async def _from_term(cls, ctx: Context, term: FieldTerm) -> SolrToken:
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
                ids = await ctx.get_ids_for_roles(t.values)
                if ids is None:
                    return st.empty()
                else:
                    nel = Nel.from_list(ids)
                    if nel is None:
                        return st.id_not_exists()
                    else:
                        return st.id_in(nel)
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

    @classmethod
    def _from_text(cls, text: Text) -> SolrToken:
        return st.content_all(text.value)

    @classmethod
    async def _from_segment(cls, ctx: Context, segment: FieldTerm | Text) -> SolrToken:
        match segment:
            case Text() as t:
                return cls._from_text(t)
            case t:
                return await cls._from_term(ctx, t)

    async def run(self, ctx: Context, q: UserQuery) -> SolrUserQuery:
        """Convert a user query into a search query."""
        (terms, sort) = q.extract_order()
        sort = sort.fields.to_list() if sort is not None else []

        solr_sort = [LuceneQueryInterpreter._to_solr_sort(e) for e in sort]
        solr_token = []
        empty = st.empty()
        for e in terms:
            t = await LuceneQueryInterpreter._from_segment(ctx, e)
            if t != empty:
                solr_token.append(t)

        return SolrUserQuery(st.fold_and(solr_token), solr_sort)
