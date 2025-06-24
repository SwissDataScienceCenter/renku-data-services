"""Functions for working with user queries."""

from __future__ import annotations

from typing import override

from renku_data_services.app_config import logging
from renku_data_services.search.user_query import (
    DirectMemberIs,
    EmptyUserQueryVisitor,
    FieldTerm,
    MemberIs,
    Nel,
    Order,
    OrderBy,
    Segment,
    Text,
    TypeIs,
    UserDef,
    UserQuery,
    UserQuerySegmentVisitor,
)
from renku_data_services.solr.entity_documents import EntityType

logger = logging.getLogger(__name__)


class ExtractOrder(UserQuerySegmentVisitor[tuple[list[FieldTerm | Text], Order | None]]):
    """Extract order from a query."""

    def __init__(self) -> None:
        self.segs: list[FieldTerm | Text] = []
        self.orders: list[OrderBy] = []

    def build(self) -> tuple[list[FieldTerm | Text], Order | None]:
        """Return the split query."""
        sort = Nel.from_list(self.orders)
        return (self.segs, Order(sort) if sort is not None else None)

    def visit_order(self, order: Order) -> None:
        """Collect order nodes."""
        self.orders.extend(order.fields.to_list())

    def visit_text(self, text: Text) -> None:
        """Collect text nodes."""
        self.segs.append(text)

    def visit_field_term(self, ft: FieldTerm) -> None:
        """Collect field term nodes."""
        self.segs.append(ft)


class CollectEntityTypes(EmptyUserQueryVisitor[set[EntityType] | None]):
    """Gather all entity types that are requested."""

    def __init__(self) -> None:
        self.result: set[EntityType] | None = None

    def visit_type_is(self, ft: TypeIs) -> None:
        """Collect type-is nodes."""
        values = set(ft.values.to_list())
        self.result = values if self.result is None else self.result.intersection(values)

    def build(self) -> set[EntityType] | None:
        """Return the collected entity types."""
        return self.result


class CollapseText(UserQuerySegmentVisitor[UserQuery]):
    """Collapses consecutive free text segments."""

    def __init__(self) -> None:
        self.segments: list[Segment] = []
        self.current: Text | None = None

    def build(self) -> UserQuery:
        """Return the modified query."""
        if self.current is not None:
            self.segments.append(self.current)
        return UserQuery(self.segments)

    def visit_text(self, text: Text) -> None:
        """Collect text nodes."""
        self.current = text if self.current is None else self.current.append(text)
        return None

    def visit_other(self, seg: Order | FieldTerm) -> None:
        """Append the current text segment and reset, then add `seg`."""
        if self.current is not None:
            self.segments.append(self.current)
            self.current = None
        self.segments.append(seg)

    def visit_order(self, order: Order) -> None:
        """Visit order nodes."""
        return self.visit_other(order)

    def visit_field_term(self, ft: FieldTerm) -> None:
        """Visit field term nodes."""
        return self.visit_other(ft)


class CollapseMembers(UserQuerySegmentVisitor[UserQuery]):
    """Collapses member segments and limits values to a maximum."""

    def __init__(self, maximum_member_count: int = 4) -> None:
        self.maximum_member_count = maximum_member_count
        self.segments: list[Segment] = []
        self.members: list[UserDef] = []
        self.direct_members: list[UserDef] = []

    def build(self) -> UserQuery:
        """Return the query with member segments combined."""
        result: list[Segment] = []
        max = self.maximum_member_count
        length = len(self.members) + len(self.direct_members)
        if length > max:
            logger.info(f"Removing {length - max} members from query, only {max} allowed!")
            self.members = self.members[:max]
            remaining = abs(max - len(self.members))
            self.direct_members = self.direct_members[:remaining]

        nel = Nel.from_list(self.members)
        if nel is not None:
            result.append(MemberIs(nel))

        nel = Nel.from_list(self.direct_members)
        if nel is not None:
            result.append(DirectMemberIs(nel))

        self.members = []
        self.direct_members = []
        self.segments.extend(result)
        return UserQuery(self.segments)

    @override
    def visit_member_is(self, ft: MemberIs) -> None:
        self.members.extend(ft.users.to_list())

    @override
    def visit_direct_member_is(self, ft: DirectMemberIs) -> None:
        self.direct_members.extend(ft.users.to_list())

    def visit_order(self, order: Order) -> None:
        """Collect order nodes."""
        self.segments.append(order)

    def visit_text(self, text: Text) -> None:
        """Collect text nodes."""
        self.segments.append(text)

    def visit_field_term(self, ft: FieldTerm) -> None:
        """Collect remaining terms."""
        self.segments.append(ft)
