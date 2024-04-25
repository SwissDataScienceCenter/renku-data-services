"""Converter of models to Avro schemas for events."""

from typing import TypeAlias, cast

from dataclasses_avroschema.schema_generator import AvroModel

from renku_data_services.authz import models as authz_models
from renku_data_services.errors import errors
from renku_data_services.message_queue import AmbiguousEvent
from renku_data_services.message_queue.avro_models.io.renku.events import v1, v2
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

        raise errors.EventError(
            message=f"Trying to convert an unknown project visibility {visibility} to message visibility"
        )

    @staticmethod
    def to_event(project: project_models.Project, event_type: type[AvroModel] | AmbiguousEvent) -> AvroModel:
        if project.id is None:
            raise errors.EventError(
                message=f"Cannot create an event of type {event_type} for a project which has no ID"
            )
        match event_type:
            case v1.ProjectCreated:
                return v1.ProjectCreated(
                    id=project.id,
                    name=project.name,
                    slug=project.slug,
                    repositories=project.repositories,
                    visibility=_ProjectEventConverter._convert_project_visibility(project.visibility),
                    description=project.description,
                    createdBy=project.created_by,
                    creationDate=project.creation_date,
                    keywords=[],
                )
            case v1.ProjectUpdated:
                return v1.ProjectUpdated(
                    id=project.id,
                    name=project.name,
                    slug=project.slug,
                    repositories=project.repositories,
                    visibility=_ProjectEventConverter._convert_project_visibility(project.visibility),
                    description=project.description,
                    keywords=[],
                )
            case v1.ProjectRemoved:
                return v1.ProjectRemoved(id=project.id)

        raise errors.EventError(message=f"Trying to convert a project to an uknown event type {event_type}")


class _UserEventConverter:
    @staticmethod
    def to_event(user: user_models.UserInfo, event_type: type[AvroModel] | AmbiguousEvent) -> AvroModel:
        match event_type:
            case v1.UserAdded:
                return v1.UserAdded(id=user.id, firstName=user.first_name, lastName=user.last_name, email=user.email)
            case v1.UserRemoved:
                return v1.UserRemoved(id=user.id)
            case v1.UserUpdated:
                return v1.UserUpdated(id=user.id, firstName=user.first_name, lastName=user.last_name, email=user.email)
        raise errors.EventError(message=f"Trying to convert a user to an uknown event type {event_type}")


class _ProjectAuthzEventConverter:
    @staticmethod
    def _convert_project_member_role(role: authz_models.Role) -> v2.MemberRole:
        match role:
            case authz_models.Role.EDITOR:
                return v2.MemberRole.EDITOR
            case authz_models.Role.VIEWER:
                return v2.MemberRole.VIEWER
            case authz_models.Role.OWNER:
                return v2.MemberRole.OWNER
        raise errors.EventError(message=f"Cannot convert role {role} to an event")

    @staticmethod
    def to_events(member_changes: list[authz_models.MembershipChange]) -> list[AvroModel]:
        output: list[AvroModel] = []
        for change in member_changes:
            match change.change:
                case authz_models.Change.UPDATE:
                    output.append(
                        v2.ProjectMemberUpdated(
                            projectId=change.member.resource_id,
                            userId=change.member.user_id,
                            role=_ProjectAuthzEventConverter._convert_project_member_role(change.member.role),
                        )
                    )
                case authz_models.Change.REMOVE:
                    output.append(
                        v2.ProjectMemberRemoved(
                            projectId=change.member.resource_id,
                            userId=change.member.user_id,
                        )
                    )
                case authz_models.Change.ADD:
                    output.append(
                        v2.ProjectMemberAdded(
                            projectId=change.member.resource_id,
                            userId=change.member.user_id,
                            role=_ProjectAuthzEventConverter._convert_project_member_role(change.member.role),
                        )
                    )
                case _:
                    raise errors.EventError(
                        message="Trying to convert a project membership change to an uknown event type with "
                        f"unkonwn change {change.change}"
                    )
        return output


_ModelTypes: TypeAlias = project_models.Project | user_models.UserInfo | list[authz_models.MembershipChange]


class EventConverter:
    """Generates event from any type of data service models."""

    @staticmethod
    def to_event(input: _ModelTypes, event_type: type[AvroModel] | AmbiguousEvent) -> list[AvroModel]:
        """Generate an event for a data service model based on an event type."""
        if isinstance(input, project_models.Project):
            input = cast(project_models.Project, input)
            return [_ProjectEventConverter.to_event(input, event_type)]
        elif isinstance(input, project_models.ProjectUpdate):
            input = cast(project_models.Project, input.new)
            return [_ProjectEventConverter.to_event(input, event_type)]
        elif isinstance(input, user_models.UserInfo):
            input = cast(user_models.UserInfo, input)
            return [_UserEventConverter.to_event(input, event_type)]
        elif (
            isinstance(input, list)
            and len(input) > 0
            and isinstance(input[0], authz_models.MembershipChange)
        ):
            input = cast(list[authz_models.MembershipChange], input)
            return _ProjectAuthzEventConverter.to_events(input)
        elif isinstance(input, list) and len(input) == 0:
            return []
        raise errors.EventError(
            message=f"Trying to convert an uknown model of type {type(input)} to an event type {event_type}"
        )
