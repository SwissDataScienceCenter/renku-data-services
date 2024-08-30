"""Converter of models to Avro schemas for events."""

from typing import TypeVar, cast

from dataclasses_avroschema.schema_generator import AvroModel

from renku_data_services.authz import models as authz_models
from renku_data_services.errors import errors
from renku_data_services.message_queue import events
from renku_data_services.message_queue.avro_models.io.renku.events import v2
from renku_data_services.message_queue.models import Event
from renku_data_services.namespace import models as group_models
from renku_data_services.project import models as project_models
from renku_data_services.users import models as user_models


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
    def to_events(
        project: project_models.Project, event_type: type[AvroModel] | type[events.AmbiguousEvent]
    ) -> list[Event]:
        if project.id is None:
            raise errors.EventError(
                message=f"Cannot create an event of type {event_type} for a project which has no ID"
            )
        project_id_str = str(project.id)
        match event_type:
            case v2.ProjectCreated:
                return [
                    Event(
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
                    Event(
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
                    Event(
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
                return [Event("project.removed", v2.ProjectRemoved(id=project_id_str))]
            case _:
                raise errors.EventError(message=f"Trying to convert a project to an unknown event type {event_type}")


class _UserEventConverter:
    @staticmethod
    def to_events(
        user: user_models.UserInfo | user_models.UserWithNamespace | user_models.UserWithNamespaceUpdate,
        event_type: type[AvroModel] | type[events.AmbiguousEvent],
    ) -> list[Event]:
        match event_type:
            case v2.UserAdded | events.InsertUserNamespace:
                user = cast(user_models.UserWithNamespace, user)
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
            case v2.UserRemoved:
                user = cast(user_models.UserInfo, user)
                return [Event("user.removed", v2.UserRemoved(id=user.id))]
            case events.UpdateOrInsertUser:
                user = cast(user_models.UserWithNamespaceUpdate, user)
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
            resource_id = str(change.member.resource_id)
            match change.change:
                case authz_models.Change.UPDATE:
                    output.append(
                        Event(
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
                        Event(
                            "projectAuth.removed",
                            v2.ProjectMemberRemoved(
                                projectId=resource_id,
                                userId=change.member.user_id,
                            ),
                        )
                    )
                case authz_models.Change.ADD:
                    output.append(
                        Event(
                            "projectAuth.added",
                            v2.ProjectMemberAdded(
                                projectId=resource_id,
                                userId=change.member.user_id,
                                role=_convert_member_role(change.member.role),
                            ),
                        )
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
                        Event(
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
                        Event(
                            "memberGroup.removed",
                            v2.GroupMemberRemoved(
                                groupId=resource_id,
                                userId=change.member.user_id,
                            ),
                        )
                    )
                case authz_models.Change.ADD:
                    output.append(
                        Event(
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
    def to_events(group: group_models.Group, event_type: type[AvroModel] | type[events.AmbiguousEvent]) -> list[Event]:
        if group.id is None:
            raise errors.ProgrammingError(
                message="Cannot send group events to the message queue for a group that does not have an ID"
            )
        group_id = str(group.id)
        match event_type:
            case v2.GroupAdded:
                return [
                    Event(
                        "group.added",
                        v2.GroupAdded(
                            id=group_id, name=group.name, description=group.description, namespace=group.slug
                        ),
                    ),
                    Event(
                        "memberGroup.added",
                        v2.GroupMemberAdded(
                            groupId=group_id,
                            userId=group.created_by,
                            role=v2.MemberRole.OWNER,
                        ),
                    ),
                ]
            case v2.GroupRemoved:
                return [Event("group.removed", v2.GroupRemoved(id=group_id))]
            case v2.GroupUpdated:
                return [
                    Event(
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
    def to_events(input: _T, event_type: type[AvroModel] | type[events.AmbiguousEvent]) -> list[Event]:
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
                user_with_namespace = cast(user_models.UserWithNamespace, input)
                return _UserEventConverter.to_events(user_with_namespace, event_type)
            case v2.UserRemoved:
                user_info = cast(user_models.UserInfo, input)
                return _UserEventConverter.to_events(user_info, event_type)
            case events.UpdateOrInsertUser:
                user_with_namespace_update = cast(user_models.UserWithNamespaceUpdate, input)
                return _UserEventConverter.to_events(user_with_namespace_update, event_type)
            case events.InsertUserNamespace:
                user_namespaces = cast(list[user_models.UserWithNamespace], input)
                output: list[Event] = []
                for namespace in user_namespaces:
                    output.extend(_UserEventConverter.to_events(namespace, event_type))
                return output
            case _:
                raise errors.EventError(message=f"Trying to convert an unknown event type {event_type}")
