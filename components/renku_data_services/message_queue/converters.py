"""Converter of models to Avro schemas for events."""

from typing import TypeAlias, cast

from dataclasses_avroschema.schema_generator import AvroModel

from renku_data_services.authz import models as authz_models
from renku_data_services.errors import errors
from renku_data_services.message_queue.avro_models.io.renku.events import v1
from renku_data_services.project import models as project_models
from renku_data_services.users import models as user_models


class _ProjectEventConverter:
    @staticmethod
    def _convert_project_visibility(visibility: project_models.Visibility) -> v1.Visibility:
        match visibility:
            case project_models.Visibility.public:
                return v1.Visibility.PUBLIC
            case project_models.Visibility.private:
                return v1.Visibility.PRIVATE

        raise errors.EventError(
            message=f"Trying to convert an unknown project visibility {visibility} to message visibility"
        )

    @staticmethod
    def to_event(project: project_models.Project, event_type: type[AvroModel]) -> AvroModel:
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
                )
            case v1.ProjectUpdated:
                return v1.ProjectUpdated(
                    id=project.id,
                    name=project.name,
                    slug=project.slug,
                    repositories=project.repositories,
                    visibility=_ProjectEventConverter._convert_project_visibility(project.visibility),
                    description=project.description,
                )
            case v1.ProjectRemoved:
                return v1.ProjectRemoved(id=project.id)

        raise errors.EventError(message=f"Trying to convert a project to an uknown event type {event_type}")


class _UserEventConverter:
    @staticmethod
    def to_event(user: user_models.UserInfo, event_type: type[AvroModel]) -> AvroModel:
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
    def _convert_project_member_role(role: authz_models.Role) -> v1.ProjectMemberRole:
        match role:
            case authz_models.Role.MEMBER:
                return v1.ProjectMemberRole.MEMBER
            case authz_models.Role.OWNER:
                return v1.ProjectMemberRole.OWNER
        raise errors.EventError(message=f"Cannot convert role {role} to an event")

    @staticmethod
    def to_event(project_member: authz_models.Member, event_type: type[AvroModel]) -> AvroModel:
        match event_type:
            case v1.ProjectAuthorizationAdded:
                return v1.ProjectAuthorizationAdded(
                    projectId=project_member.project_id,
                    userId=project_member.user_id,
                    role=_ProjectAuthzEventConverter._convert_project_member_role(project_member.role),
                )
            case v1.ProjectAuthorizationRemoved:
                return v1.ProjectAuthorizationRemoved(
                    projectId=project_member.project_id,
                    userId=project_member.user_id,
                )
            case v1.ProjectAuthorizationUpdated:
                return v1.ProjectAuthorizationAdded(
                    projectId=project_member.project_id,
                    userId=project_member.user_id,
                    role=_ProjectAuthzEventConverter._convert_project_member_role(project_member.role),
                )
        raise errors.EventError(message=f"Trying to convert a project member to an uknown event type {event_type}")


_ModelTypes: TypeAlias = project_models.Project | user_models.UserInfo | authz_models.Member


class EventConverter:
    """Generates event from any type of data service models."""

    @staticmethod
    def to_event(input: _ModelTypes, event_type: type[AvroModel]) -> AvroModel:
        """Generate an event for a data service model based on an event type."""
        match type(input):
            case project_models.Project:
                input = cast(project_models.Project, input)
                return _ProjectEventConverter.to_event(input, event_type)
            case user_models.UserInfo:
                input = cast(user_models.UserInfo, input)
                return _UserEventConverter.to_event(input, event_type)
            case authz_models.Member:
                input = cast(authz_models.Member, input)
                return _ProjectAuthzEventConverter.to_event(input, event_type)
        raise errors.EventError(
            message=f"Trying to convert an uknown model of type {type(input)} to an event type {event_type}"
        )
