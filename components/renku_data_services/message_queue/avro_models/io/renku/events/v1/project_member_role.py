from enum import Enum


class ProjectMemberRole(Enum):
    """
    Access role of a project member
    """
    MEMBER = 'MEMBER'
    OWNER = 'OWNER'
