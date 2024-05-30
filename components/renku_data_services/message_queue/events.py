"""Message queue classes."""


class AmbiguousEvent:
    """Indicates events that don't have a specific avro model."""


class ProjectMembershipChanged(AmbiguousEvent):
    """Event for changes in project members."""


class GroupMembershipChanged(AmbiguousEvent):
    """Event for changes in group members."""


class UpdateOrInsertUser(AmbiguousEvent):
    """Event for adding or updating users."""


class InsertUserNamespace(AmbiguousEvent):
    """Event for adding user namespcaes."""
