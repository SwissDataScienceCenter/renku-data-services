from enum import Enum


class MemberRole(Enum):
    """
    Access role of a member
    """
    OWNER = 'OWNER'
    EDITOR = 'EDITOR'
    VIEWER = 'VIEWER'
