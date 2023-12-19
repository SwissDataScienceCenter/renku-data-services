"""Models for projects."""

from dataclasses import dataclass
from enum import Enum
from typing import List

from sqlalchemy.sql import ColumnExpressionArgument

from renku_data_services.authz.orm import ProjectUserAuthz


class Role(Enum):
    """
    Project membership role.

    Higher values have more access than lower values and
    all higher values include the permissions from lower access levels.
    For example an owner (value 80) is also a member (values 40) and has
    public access permissions (value 0) on the project.
    """

    MEMBER: int = 40
    OWNER: int = 80

    def sql_access_test(self) -> ColumnExpressionArgument[bool]:
        """Get the SQL logical tests to enforce the member roles."""
        return ProjectUserAuthz.role >= self.value


class MemberQualifier(Enum):
    """Used to express additional intent or details about permission decisions."""

    ALL: str = "all"
    SOME: str = "some"
    NONE: str = "none"

    def sql_access_test(self, user_ids: List[str]) -> ColumnExpressionArgument[bool]:
        """Get the SQL logical tests to enforce the permissions."""
        match self:
            case MemberQualifier.ALL:
                if len(user_ids) > 0:
                    raise ValueError("Cannot use 'ALL' member qualifier with specific users")
                return ProjectUserAuthz.user_id.is_(None)
            case MemberQualifier.SOME:
                if len(user_ids) == 0:
                    raise ValueError("Cannot use 'SOME' member qualifier with no users")
                return ProjectUserAuthz.user_id.in_(user_ids)
            case MemberQualifier.NONE:
                # NOTE: This is very unlikely to be used when querying permissions tests
                raise NotImplementedError("Using 'NONE' for access testing has not been implemented")


class Scope(Enum):
    """Types of permissions - i.e. scope."""

    READ: str = "read"
    WRITE: str = "write"
    DELETE: str = "delete"

    def _least_authorized_member(self) -> Role:
        """Get the least-powerful member type that has the required scope on the project."""
        scope_role_xref = {
            Scope.WRITE: Role.OWNER,
            Scope.READ: Role.MEMBER,
            Scope.DELETE: Role.OWNER,
        }
        return scope_role_xref[self]

    def sql_access_test(self) -> ColumnExpressionArgument[bool]:
        """Get the SQL logical tests to enforce the permissions."""
        return self._least_authorized_member().sql_access_test()


@dataclass
class ProjectMember:
    """A class to hold a user and her role."""

    role: Role
    user_id: str
