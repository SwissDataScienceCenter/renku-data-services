"""Converter of models to Avro schemas for events."""

from typing import TypeVar

from dataclasses_avroschema.schema_generator import AvroModel

from renku_data_services.authz import models as authz_models
from renku_data_services.errors import errors
from renku_data_services.message_queue import AmbiguousEvent
from renku_data_services.message_queue.avro_models.io.renku.events import v1, v2
from renku_data_services.message_queue.models import Event
from renku_data_services.namespace.models import Group
from renku_data_services.project import models as project_models
from renku_data_services.users import models as user_models


class _ProjectEventConverter:
    @staticmethod
    def _convert_project_visibility(visibility: authz_models.Visibility) -> v1.Visibility:
        match visibility:
            case authz_models.Visibility.PUBLIC:
                return v1.Visibility.PUBLIC
            case authz_models.Visibility.PRIVATE:
                return v1.Visibility.PRIVATE
            case _:
                raise errors.EventError(
                    message=f"Trying to convert an unknown project visibility {visibility} to message visibility"
                )

    @staticmethod
    def _convert_project_visibility_v2(visibility: authz_models.Visibility) -> v2.Visibility:
        match visibility:
            case authz_models.Visibility.PUBLIC:
                return v2.Visibility.PUBLIC
            case authz_models.Visibility.PRIVATE:
                return v2.Visibility.PRIVATE
            case _:
                raise errors.EventError(
                    message=f"Trying to convert an unknown project visibility {visibility} to message visibility"
                )

    @staticmethod
    def to_events(project: project_models.Project, event_type: type[AvroModel] | AmbiguousEvent) -> list[Event]:
        if project.id is None:
            raise errors.EventError(
                message=f"Cannot create an event of type {event_type} for a project which has no ID"
            )
        match event_type:
            case v2.ProjectCreated:
                return [
                    Event(
                        "project.created",
                        v2.ProjectCreated(
                            id=project.id,
                            name=project.name,
                            namespace=project.namespace.slug,
                            slug=project.slug,
                            repositories=project.repositories,
                            visibility=_ProjectEventConverter._convert_project_visibility_v2(project.visibility),
                            description=project.description,
                            createdBy=project.created_by,
                            creationDate=project.creation_date,
                            keywords=project.keywords or [],
                        ),
                    ),
                    Event(
                        "projectAuth.added",
                        v2.ProjectMemberAdded(
                            projectId=project.id,
                            userId=project.created_by,
                            role=v2.MemberRole.OWNER,
                        ),
                    ),
                ]
            case v2.ProjectUpdated:
                return [
                    Event(
                        "project.updated",
                        v2.ProjectUpdated(
                            id=project.id,
                            name=project.name,
                            namespace=project.namespace.slug,
                            slug=project.slug,
                            repositories=project.repositories,
                            visibility=_ProjectEventConverter._convert_project_visibility_v2(project.visibility),
                            description=project.description,
                            keywords=project.keywords or [],
                        ),
                    )
                ]
            case v2.ProjectRemoved:
                return [Event("project.removed", v2.ProjectRemoved(id=project.id))]
            case _:
                raise errors.EventError(message=f"Trying to convert a project to an unknown event type {event_type}")


class _UserEventConverter:
    @staticmethod
    def to_events(
        user: user_models.UserInfo | user_models.UserWithNamespace | user_models.UserWithNamespaceUpdate,
        event_type: type[AvroModel] | AmbiguousEvent,
    ) -> list[Event]:
        match event_type:
            case v2.UserAdded | AmbiguousEvent.INSERT_USER_NAMESPACE if isinstance(user, user_models.UserWithNamespace):
                return [
                    Event(
                        "user.added",
                        v2.UserAdded(
                            id=user.user.id,
                            firstName=user.user.first_name,
                            lastName=user.user.last_name,
                            email=user.user.email,
                            namespace=user.namespace.slug,
                        ),
                    )
                ]
            case v2.UserRemoved if isinstance(user, user_models.UserInfo):
                return [Event("user.removed", v2.UserRemoved(id=user.id))]
            case AmbiguousEvent.UPDATE_OR_INSERT_USER if isinstance(user, user_models.UserWithNamespaceUpdate):
                return [
                    Event(
                        "user.added" if user.old is None else "user.updated",
                        v2.UserAdded(
                            id=user.new.user.id,
                            firstName=user.new.user.first_name,
                            lastName=user.new.user.last_name,
                            email=user.new.user.email,
                            namespace=user.new.namespace.slug,
                        ),
                    )
                ]
            case _:
                raise errors.EventError(
                    message=f"Trying to convert a user of type {type(user)} to an unknown event type {event_type}"
                )


def _convert_member_role(role: authz_models.Role) -> v2.MemberRole:
    match role:
        case authz_models.Role.EDITOR:
            return v2.MemberRole.EDITOR
        case authz_models.Role.VIEWER:
            return v2.MemberRole.VIEWER
        case authz_models.Role.OWNER:
            return v2.MemberRole.OWNER
        case _:
            raise errors.EventError(message=f"Cannot convert role {role} to an event")


class _ProjectAuthzEventConverter:
    @staticmethod
    def to_events(member_changes: list[authz_models.MembershipChange]) -> list[Event]:
        output: list[Event] = []
        for change in member_changes:
            match change.change:
                case authz_models.Change.UPDATE:
                    output.append(
                        Event(
                            "projectAuth.updated",
                            v2.ProjectMemberUpdated(
                                projectId=change.member.resource_id,
                                userId=change.member.user_id,
                                role=_convert_member_role(change.member.role),
                            ),
                        )
                    )
                case authz_models.Change.REMOVE:
                    output.append(
                        Event(
                            "projectAuth.removed",
                            v2.ProjectMemberRemoved(
                                projectId=change.member.resource_id,
                                userId=change.member.user_id,
                            ),
                        )
                    )
                case authz_models.Change.ADD:
                    output.append(
                        Event(
                            "projectAuth.added",
                            v2.ProjectMemberAdded(
                                projectId=change.member.resource_id,
                                userId=change.member.user_id,
                                role=_convert_member_role(change.member.role),
                            ),
                        )
                    )
                case _:
                    raise errors.EventError(
                        message="Trying to convert a project membership change to an unknown event type with "
                        f"unkonwn change {change.change}"
                    )
        return output


class _GroupAuthzEventConverter:
    @staticmethod
    def to_events(member_changes: list[authz_models.MembershipChange]) -> list[Event]:
        output: list[Event] = []
        for change in member_changes:
            match change.change:
                case authz_models.Change.UPDATE:
                    output.append(
                        Event(
                            "memberGroup.updated",
                            v2.ProjectMemberUpdated(
                                projectId=change.member.resource_id,
                                userId=change.member.user_id,
                                role=_convert_member_role(change.member.role),
                            ),
                        )
                    )
                case authz_models.Change.REMOVE:
                    output.append(
                        Event(
                            "memberGroup.removed",
                            v2.ProjectMemberRemoved(
                                projectId=change.member.resource_id,
                                userId=change.member.user_id,
                            ),
                        )
                    )
                case authz_models.Change.ADD:
                    output.append(
                        Event(
                            "memberGroup.added",
                            v2.ProjectMemberAdded(
                                projectId=change.member.resource_id,
                                userId=change.member.user_id,
                                role=_convert_member_role(change.member.role),
                            ),
                        )
                    )
                case _:
                    raise errors.EventError(
                        message="Trying to convert a project membership change to an unknown event type with "
                        f"unkonwn change {change.change}"
                    )
        return output


class _GroupEventConverter:
    @staticmethod
    def to_events(input: Group, event_type: type[AvroModel] | AmbiguousEvent) -> list[Event]:
        if input.id is None:
            raise errors.ProgrammingError(
                message="Cannot send group events to the message queue for a group that does not have an ID"
            )
        match event_type:
            case v2.GroupAdded:
                return [
                    Event(
                        "group.added",
                        v2.GroupAdded(
                            id=input.id, name=input.name, description=input.description, namespace=input.slug
                        ),
                    )
                ]
            case v2.GroupRemoved:
                return [Event("group.removed", v2.GroupRemoved(id=input.id))]
            case v2.GroupUpdated:
                return [
                    Event(
                        "group.updated",
                        v2.GroupUpdated(
                            id=input.id, name=input.name, description=input.description, namespace=input.slug
                        ),
                    )
                ]
            case _:
                raise errors.ProgrammingError(
                    message=f"Received an unknown event type {event_type} when generating group events"
                )


_T = TypeVar("_T")


class EventConverter:
    """Generates events from any type of data service models."""

    @staticmethod
    def to_events(input: _T, event_type: type[AvroModel] | AmbiguousEvent) -> list[Event]:
        """Generate an event for a data service model based on an event type."""
        if isinstance(input, project_models.Project):
            return _ProjectEventConverter.to_events(input, event_type)
        elif isinstance(input, project_models.ProjectUpdate):
            return _ProjectEventConverter.to_events(input.new, event_type)
        elif isinstance(input, (user_models.UserInfo, user_models.UserWithNamespace)):
            return _UserEventConverter.to_events(input, event_type)
        elif input is None and event_type == type(v2.UserRemoved):  # type: ignore[unreachable]
            # NOTE: The user that was supposed to be removed is not in the database at all, so dont send the event
            # The code is definitely reachable it is just that mypy thinks it is not
            return []  # type: ignore[unreachable]
        elif (
            isinstance(input, list)
            and len(input) > 0
            and all([isinstance(i, authz_models.MembershipChange) for i in input])
        ):
            if event_type == AmbiguousEvent.PROJECT_MEMBERSHIP_CHANGED:
                return _ProjectAuthzEventConverter.to_events(input)
            elif event_type == AmbiguousEvent.GROUP_MEMBERSHIP_CHANGED:
                return _GroupAuthzEventConverter.to_events(input)
            else:
                raise errors.ProgrammingError(
                    message="Found unknown event type when processing membership change list in the message queue "
                    f"decorator, {type(event_type)}"
                )
        elif isinstance(input, list) and len(input) == 0:
            return []
        elif (
            isinstance(input, user_models.UserWithNamespaceUpdate)
            and event_type == AmbiguousEvent.UPDATE_OR_INSERT_USER
        ):
            return _UserEventConverter.to_events(input, event_type)
        elif (
            isinstance(input, list)
            and event_type == AmbiguousEvent.INSERT_USER_NAMESPACE
            and len(input) > 0
            and all([isinstance(i, user_models.UserWithNamespace) for i in input])
        ):
            output: list[Event] = []
            for namespace in input:
                output.extend(_UserEventConverter.to_events(namespace, event_type))
            return output
        elif isinstance(input, Group):
            return _GroupEventConverter.to_events(input, event_type)
        else:
            raise errors.EventError(
                message=f"Trying to convert an unknown model of type {type(input)} to an event type {event_type}"
            )
