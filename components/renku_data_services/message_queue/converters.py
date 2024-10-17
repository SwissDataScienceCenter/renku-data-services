"""Converter of models to Avro schemas for events."""

from typing import Final, TypeVar, cast

from dataclasses_avroschema import AvroModel

from renku_data_services.authz import models as authz_models
from renku_data_services.errors import errors
from renku_data_services.message_queue import events
from renku_data_services.message_queue.avro_models.io.renku.events import v2
from renku_data_services.message_queue.models import Event
from renku_data_services.namespace import models as group_models
from renku_data_services.project import models as project_models
from renku_data_services.users import models as user_models

QUEUE_NAME: Final[str] = "data_service.all_events"
_EventType = TypeVar("_EventType", type[AvroModel], type[events.AmbiguousEvent], covariant=True)


def make_event(message_type: str, payload: AvroModel) -> Event:
    """Create an event."""
    return Event.create(QUEUE_NAME, message_type, payload)


def make_project_member_added_event(member: authz_models.Member) -> Event:
    """Create a ProjectMemberAdded event."""
    payload = v2.ProjectMemberAdded(
        projectId=str(member.resource_id), userId=member.user_id, role=_convert_member_role(member.role)
    )
    return make_event("projectAuth.added", payload)


def make_group_member_added_event(member: authz_models.Member) -> Event:
    """Create a GroupMemberAdded event."""
    payload = v2.GroupMemberAdded(
        groupId=str(member.resource_id), userId=member.user_id, role=_convert_member_role(member.role)
    )
    return make_event("memberGroup.added", payload)


class _ProjectEventConverter:
    @staticmethod
    def _convert_project_visibility(visibility: authz_models.Visibility) -> v2.Visibility:
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
    def to_events(project: project_models.Project, event_type: _EventType) -> list[Event]:
        if project.id is None:
            raise errors.EventError(
                message=f"Cannot create an event of type {event_type} for a project which has no ID"
            )
        project_id_str = str(project.id)
        match event_type:
            case v2.ProjectCreated:
                return [
                    make_event(
                        "project.created",
                        v2.ProjectCreated(
                            id=project_id_str,
                            name=project.name,
                            namespace=project.namespace.slug,
                            slug=project.slug,
                            repositories=project.repositories,
                            visibility=_ProjectEventConverter._convert_project_visibility(project.visibility),
                            description=project.description,
                            createdBy=project.created_by,
                            creationDate=project.creation_date,
                            keywords=project.keywords or [],
                        ),
                    ),
                    make_event(
                        "projectAuth.added",
                        v2.ProjectMemberAdded(
                            projectId=project_id_str,
                            userId=project.created_by,
                            role=v2.MemberRole.OWNER,
                        ),
                    ),
                ]
            case v2.ProjectUpdated:
                return [
                    make_event(
                        "project.updated",
                        v2.ProjectUpdated(
                            id=project_id_str,
                            name=project.name,
                            namespace=project.namespace.slug,
                            slug=project.slug,
                            repositories=project.repositories,
                            visibility=_ProjectEventConverter._convert_project_visibility(project.visibility),
                            description=project.description,
                            keywords=project.keywords or [],
                        ),
                    )
                ]
            case v2.ProjectRemoved:
                return [make_event("project.removed", v2.ProjectRemoved(id=project_id_str))]
            case _:
                raise errors.EventError(message=f"Trying to convert a project to an unknown event type {event_type}")


class _UserEventConverter:
    @staticmethod
    def to_events(user: user_models.UserInfo | user_models.UserInfoUpdate | str, event_type: _EventType) -> list[Event]:
        match event_type:
            case v2.UserAdded | events.InsertUserNamespace:
                user = cast(user_models.UserInfo, user)
                return [
                    make_event(
                        "user.added",
                        v2.UserAdded(
                            id=user.id,
                            firstName=user.first_name,
                            lastName=user.last_name,
                            email=user.email,
                            namespace=user.namespace.slug,
                        ),
                    )
                ]
            case v2.UserRemoved:
                user = cast(user_models.UserInfo, user)
                return [make_event("user.removed", v2.UserRemoved(id=user.id))]
            case events.UpdateOrInsertUser:
                user = cast(user_models.UserInfoUpdate, user)
                if user.old is None:
                    return [
                        make_event(
                            "user.added",
                            v2.UserAdded(
                                id=user.new.id,
                                firstName=user.new.first_name,
                                lastName=user.new.last_name,
                                email=user.new.email,
                                namespace=user.new.namespace.slug,
                            ),
                        )
                    ]
                else:
                    return [
                        make_event(
                            "user.updated",
                            v2.UserUpdated(
                                id=user.new.id,
                                firstName=user.new.first_name,
                                lastName=user.new.last_name,
                                email=user.new.email,
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
            resource_id = str(change.member.resource_id)
            match change.change:
                case authz_models.Change.UPDATE:
                    output.append(
                        make_event(
                            "projectAuth.updated",
                            v2.ProjectMemberUpdated(
                                projectId=resource_id,
                                userId=change.member.user_id,
                                role=_convert_member_role(change.member.role),
                            ),
                        )
                    )
                case authz_models.Change.REMOVE:
                    output.append(
                        make_event(
                            "projectAuth.removed",
                            v2.ProjectMemberRemoved(
                                projectId=resource_id,
                                userId=change.member.user_id,
                            ),
                        )
                    )
                case authz_models.Change.ADD:
                    output.append(
                        make_project_member_added_event(change.member),
                    )
                case _:
                    raise errors.EventError(
                        message="Trying to convert a project membership change to an unknown event type with "
                        f"unknown change {change.change}"
                    )
        return output


class _GroupAuthzEventConverter:
    @staticmethod
    def to_events(member_changes: list[authz_models.MembershipChange]) -> list[Event]:
        output: list[Event] = []
        for change in member_changes:
            resource_id = str(change.member.resource_id)
            match change.change:
                case authz_models.Change.UPDATE:
                    output.append(
                        make_event(
                            "memberGroup.updated",
                            v2.GroupMemberUpdated(
                                groupId=resource_id,
                                userId=change.member.user_id,
                                role=_convert_member_role(change.member.role),
                            ),
                        )
                    )
                case authz_models.Change.REMOVE:
                    output.append(
                        make_event(
                            "memberGroup.removed",
                            v2.GroupMemberRemoved(
                                groupId=resource_id,
                                userId=change.member.user_id,
                            ),
                        )
                    )
                case authz_models.Change.ADD:
                    output.append(
                        make_event(
                            "memberGroup.added",
                            v2.GroupMemberAdded(
                                groupId=resource_id,
                                userId=change.member.user_id,
                                role=_convert_member_role(change.member.role),
                            ),
                        )
                    )
                case _:
                    raise errors.EventError(
                        message="Trying to convert a group membership change to an unknown event type with "
                        f"unknown change {change.change}"
                    )
        return output


class _GroupEventConverter:
    @staticmethod
    def to_events(group: group_models.Group, event_type: _EventType) -> list[Event]:
        if group.id is None:
            raise errors.ProgrammingError(
                message="Cannot send group events to the message queue for a group that does not have an ID"
            )
        group_id = str(group.id)
        match event_type:
            case v2.GroupAdded:
                return [
                    make_event(
                        "group.added",
                        v2.GroupAdded(
                            id=group_id, name=group.name, description=group.description, namespace=group.slug
                        ),
                    ),
                    make_event(
                        "memberGroup.added",
                        v2.GroupMemberAdded(
                            groupId=group_id,
                            userId=group.created_by,
                            role=v2.MemberRole.OWNER,
                        ),
                    ),
                ]
            case v2.GroupRemoved:
                return [make_event("group.removed", v2.GroupRemoved(id=group_id))]
            case v2.GroupUpdated:
                return [
                    make_event(
                        "group.updated",
                        v2.GroupUpdated(
                            id=group_id, name=group.name, description=group.description, namespace=group.slug
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
    def to_events(input: _T, event_type: _EventType) -> list[Event]:
        """Generate an event for a data service model based on an event type."""
        if not input:
            return []

        match event_type:
            case v2.ProjectCreated | v2.ProjectRemoved:
                project = cast(project_models.Project, input)
                return _ProjectEventConverter.to_events(project, event_type)
            case v2.ProjectUpdated:
                project_update = cast(project_models.ProjectUpdate, input)
                project = project_update.new
                return _ProjectEventConverter.to_events(project, event_type)
            case events.ProjectMembershipChanged:
                project_authz = cast(list[authz_models.MembershipChange], input)
                return _ProjectAuthzEventConverter.to_events(project_authz)
            case v2.GroupAdded | v2.GroupUpdated | v2.GroupRemoved:
                group = cast(group_models.Group, input)
                return _GroupEventConverter.to_events(group, event_type)
            case events.GroupMembershipChanged:
                group_authz = cast(list[authz_models.MembershipChange], input)
                return _GroupAuthzEventConverter.to_events(group_authz)
            case v2.UserAdded:
                user_with_namespace = cast(user_models.UserInfo, input)
                return _UserEventConverter.to_events(user_with_namespace, event_type)
            case v2.UserRemoved:
                user_info = cast(user_models.UserInfo, input)
                return _UserEventConverter.to_events(user_info, event_type)
            case events.UpdateOrInsertUser:
                user_with_namespace_update = cast(user_models.UserInfoUpdate, input)
                return _UserEventConverter.to_events(user_with_namespace_update, event_type)
            case events.InsertUserNamespace:
                user_namespaces = cast(list[user_models.UserInfo], input)
                output: list[Event] = []
                for namespace in user_namespaces:
                    output.extend(_UserEventConverter.to_events(namespace, event_type))
                return output
            case _:
                raise errors.EventError(message=f"Trying to convert an unknown event type {event_type}")
