"""Creating queries for solr given a parsed user search query."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from typing import override

import renku_data_services.search.solr_token as st
from renku_data_services.authz.models import Role
from renku_data_services.base_models.core import APIUser
from renku_data_services.base_models.nel import Nel
from renku_data_services.search.solr_token import SolrToken
from renku_data_services.search.user_query import (
    Comparison,
    Created,
    CreatedByIs,
    DirectMemberIs,
    DoiIs,
    IdIs,
    InheritedMemberIs,
    KeywordIs,
    NameIs,
    NamespaceIs,
    Order,
    OrderBy,
    PublisherNameIs,
    RoleIs,
    SlugIs,
    SortableField,
    Text,
    TypeIs,
    UserDef,
    UserId,
    Username,
    UserQuery,
    UserQueryVisitor,
    VisibilityIs,
)
from renku_data_services.search.user_query_process import CollectEntityTypes
from renku_data_services.solr.entity_documents import EntityType
from renku_data_services.solr.entity_schema import Fields
from renku_data_services.solr.solr_client import SortDirection
from renku_data_services.solr.solr_schema import FieldName
from renku_data_services.users.db import UsernameResolver


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
    async def get_ids_for_role(
        self, user_id: str, roles: Nel[Role], ets: Iterable[EntityType], direct_membership: bool
    ) -> list[str]:
        """Return resource ids for which the given user has the given role."""
        ...

    @classmethod
    def none(cls) -> AuthAccess:
        """An implementation returning no access."""
        return _NoAuthAccess()


class _NoAuthAccess(AuthAccess):
    async def get_ids_for_role(
        self, user_id: str, roles: Nel[Role], ets: Iterable[EntityType], direct_membership: bool
    ) -> list[str]:
        return []


class UsernameResolve(ABC):
    """Resolve usernames to their ids."""

    @abstractmethod
    async def resolve_usernames(self, names: Nel[Username]) -> dict[Username, UserId]:
        """Return the user id for a given user name."""
        ...

    @classmethod
    def none(cls) -> UsernameResolve:
        """An implementation that doesn't resolve names."""
        return _EmptyUsernameResolve()

    @classmethod
    def db(cls, repo: UsernameResolver) -> UsernameResolve:
        """An implementation using the resolver from the user module."""
        return _DbUsernameResolve(repo)


class _EmptyUsernameResolve(UsernameResolve):
    @override
    async def resolve_usernames(self, names: Nel[Username]) -> dict[Username, UserId]:
        return {}


class _DbUsernameResolve(UsernameResolve):
    def __init__(self, resolver: UsernameResolver) -> None:
        self._resolver = resolver

    async def resolve_usernames(self, names: Nel[Username]) -> dict[Username, UserId]:
        """Return the user id for a given user name."""
        result = {}
        for k, v in (await self._resolver.resolve_usernames(names.map(lambda n: n.slug.value))).items():
            result.update({Username.from_name(k): UserId(v)})

        return result


@dataclass
class Context:
    """Contextual information available at search time.

    A single context is meant to be created for interpreting a single query.
    """

    current_time: datetime
    zone: tzinfo
    role: SearchRole | None
    auth_access: AuthAccess = field(default_factory=AuthAccess.none)
    username_resolve: UsernameResolve = field(default_factory=UsernameResolve.none)
    requested_entity_types: set[EntityType] | None = None

    def __copy(
        self,
        role: SearchRole | None = None,
        auth_access: AuthAccess | None = None,
        username_resolve: UsernameResolve | None = None,
        requested_entity_types: set[EntityType] | None = None,
    ) -> Context:
        return Context(
            self.current_time,
            self.zone,
            role or self.role,
            auth_access or self.auth_access,
            username_resolve or self.username_resolve,
            requested_entity_types=requested_entity_types,
        )

    async def with_requested_entity_types(self, uq: UserQuery) -> Context:
        """Return a copy with the requested entity types set."""
        et = await uq.accept(CollectEntityTypes())
        return self if self.requested_entity_types == et else self.__copy(requested_entity_types=et)

    def with_role(self, role: SearchRole) -> Context:
        """Return a copy wit the given role set."""
        return self if self.role == role else self.__copy(role=role)

    def with_user_role(self, user_id: str) -> Context:
        """Return a copy with the given user id as user role set."""
        return self if self.role == UserRole(user_id) else self.__copy(role=UserRole(user_id))

    def with_admin_role(self, user_id: str) -> Context:
        """Return a copy with the given user id as admin role set."""
        return self if self.role == AdminRole(user_id) else self.__copy(role=AdminRole(user_id))

    def with_anonymous(self) -> Context:
        """Return a copy with no search role set."""
        return self if self.role is None else self.__copy(role=None)

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
        return self.__copy(auth_access=aa)

    def with_username_resolve(self, ur: UsernameResolve) -> Context:
        """Return a copy with the given UsernameResolve set."""
        return self.__copy(username_resolve=ur)

    def get_entity_types(self) -> list[EntityType]:
        """Return the list of entity types that are requested from the query."""
        return [e for e in EntityType] if self.requested_entity_types is None else list(self.requested_entity_types)

    async def get_ids_for_roles(self, roles: Nel[Role], direct_membership: bool) -> list[str] | None:
        """Return a list of ids the user has one of the given roles.

        Return None when anonymous.
        """
        ets = self.get_entity_types()
        match self.role:
            case UserRole() as r:
                return await self.auth_access.get_ids_for_role(r.id, roles, ets, direct_membership)
            case AdminRole() as r:
                return await self.auth_access.get_ids_for_role(r.id, roles, ets, direct_membership)
            case _:
                return None

    async def get_member_ids(self, users: Nel[UserDef], direct_membership: bool) -> list[str]:
        """Return a list of resource ids, all given users are members of."""
        result: set[str] = set()
        ids: set[UserId] = set()
        names: set[Username] = set()
        ets = self.get_entity_types()
        for user_def in users:
            match user_def:
                case Username() as u:
                    names.add(u)

                case UserId() as u:
                    ids.add(u)

        match Nel.from_list(list(names)):
            case None:
                pass
            case nel:
                remain_ids = await self.username_resolve.resolve_usernames(nel)
                ids.update(remain_ids.values())

        for uid in ids:
            n = await self.auth_access.get_ids_for_role(uid.id, Nel.of(Role.VIEWER), ets, direct_membership)
            result = set(n) if result == set() else result.intersection(set(n))

        return list(result)

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


class _LuceneQueryTransform(UserQueryVisitor[SolrUserQuery]):
    """Transform a UserQuery into a SolrUserQuery."""

    def __init__(self, ctx: Context) -> None:
        self.solr_sort: list[tuple[FieldName, SortDirection]] = []
        self.solr_token: list[SolrToken] = []
        self.ctx = ctx

    async def build(self) -> SolrUserQuery:
        """Create and return the solr query."""
        return SolrUserQuery(st.fold_and(self.solr_token), self.solr_sort)

    async def visit_order(self, order: Order) -> None:
        """Process order."""
        sort = [self._to_solr_sort(e) for e in order.fields]
        self.solr_sort.extend(sort)

    @classmethod
    def _to_solr_sort(cls, ob: OrderBy) -> tuple[FieldName, SortDirection]:
        match ob.field:
            case SortableField.fname:
                return (Fields.name, ob.direction)
            case SortableField.score:
                return (Fields.score, ob.direction)
            case SortableField.created:
                return (Fields.creation_date, ob.direction)

    def __append(self, t: SolrToken) -> None:
        self.solr_token.append(t)

    async def visit_text(self, text: Text) -> None:
        """Process free text segment."""
        if text.value != "":
            self.__append(st.content_all(text.value))

    async def visit_type_is(self, ft: TypeIs) -> None:
        """Process type-is segment."""
        self.__append(st.field_is_any(Fields.entity_type, ft.values.map(st.from_entity_type)))

    async def visit_id_is(self, ft: IdIs) -> None:
        """Process id-is segment."""
        self.__append(st.field_is_any(Fields.id, ft.values.map(st.from_str)))

    async def visit_name_is(self, ft: NameIs) -> None:
        """Process name-is segment."""
        self.__append(st.field_is_any(Fields.name, ft.values.map(st.from_str)))

    async def visit_slug_is(self, ft: SlugIs) -> None:
        """Process slug-is segment."""
        self.__append(st.field_is_any(Fields.slug, ft.values.map(st.from_str)))

    async def visit_doi_is(self, ft: DoiIs) -> None:
        """Process doi-is segment."""
        self.__append(st.field_is_any(Fields.doi, ft.values.map(st.from_str)))

    async def visit_publisher_name_is(self, ft: PublisherNameIs) -> None:
        """Process publisher_name-is segment."""
        self.__append(st.field_is_any(Fields.publisher_name, ft.values.map(st.from_str)))

    async def visit_visibility_is(self, ft: VisibilityIs) -> None:
        """Process visibility-is segment."""
        self.__append(st.field_is_any(Fields.visibility, ft.values.map(st.from_visibility)))

    async def visit_keyword_is(self, ft: KeywordIs) -> None:
        """Process keyword-is segment."""
        self.__append(st.field_is_any(Fields.keywords, ft.values.map(st.from_str)))

    async def visit_namespace_is(self, ft: NamespaceIs) -> None:
        """Process the namespace-is segment."""
        self.__append(st.namespace_path_is_any(ft.values))

    async def visit_created_by_is(self, ft: CreatedByIs) -> None:
        """Process the created-by segment."""
        self.__append(st.field_is_any(Fields.created_by, ft.values.map(st.from_str)))

    async def visit_role_is(self, ft: RoleIs) -> None:
        """Process role-is segment."""
        ids = await self.ctx.get_ids_for_roles(ft.values, direct_membership=True)
        if ids is not None:
            nel = Nel.from_list(ids)
            if nel is None:
                self.__append(st.id_not_exists())
            else:
                self.__append(st.id_in(nel))

    async def visit_inherited_member_is(self, ft: InheritedMemberIs) -> None:
        """Process inherited-member-is segment."""
        ids = await self.ctx.get_member_ids(ft.users, direct_membership=False)
        match Nel.from_list(ids):
            case None:
                self.__append(st.id_not_exists())
            case nel:
                self.__append(st.id_in(nel))

    async def visit_direct_member_is(self, ft: DirectMemberIs) -> None:
        """Process direct-member-is segment."""
        ids = await self.ctx.get_member_ids(ft.users, direct_membership=True)
        match Nel.from_list(ids):
            case None:
                self.__append(st.id_not_exists())
            case nel:
                self.__append(st.id_in(nel))

    async def visit_created(self, ft: Created) -> None:
        """Process the created segment."""
        tokens: list[SolrToken] = []
        match ft.cmp:
            case Comparison.is_equal:
                for dt in ft.values:
                    (min, max_opt) = dt.resolve(self.ctx.current_time, self.ctx.zone)
                    tokens.append(st.created_range(min, max_opt) if max_opt is not None else st.created_is(min))

                self.__append(st.fold_or(tokens))

            case Comparison.is_greater_than:
                for dt in ft.values:
                    (min, max_opt) = dt.resolve(self.ctx.current_time, self.ctx.zone)
                    tokens.append(st.created_gt(max_opt or min))

                self.__append(st.fold_or(tokens))

            case Comparison.is_lower_than:
                for dt in ft.values:
                    (min, _) = dt.resolve(self.ctx.current_time, self.ctx.zone)
                    tokens.append(st.created_lt(min))

                self.__append(st.fold_or(tokens))


class LuceneQueryInterpreter(QueryInterpreter):
    """Convert a user search query into solrs standard query.

    See https://solr.apache.org/guide/solr/latest/query-guide/standard-query-parser.html

    This class takes care of converting a user supplied query into the
    corresponding solr query.

    Here the search query can be tweaked if necessary (fuzzy searching
    etc).

    """

    async def run(self, ctx: Context, q: UserQuery) -> SolrUserQuery:
        """Convert a user query into a solr search query."""

        return await q.accept(_LuceneQueryTransform(ctx))
