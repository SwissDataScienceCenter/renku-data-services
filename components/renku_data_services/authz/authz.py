"""Projects authorization adapter."""

from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from functools import wraps
from typing import ClassVar, Protocol

from authzed.api.v1 import (
    CheckPermissionRequest,
    CheckPermissionResponse,
    Client,
    Consistency,
    LookupResourcesRequest,
    LookupResourcesResponse,
    LookupSubjectsRequest,
    LookupSubjectsResponse,
    ObjectReference,
    ReadRelationshipsRequest,
    ReadRelationshipsResponse,
    Relationship,
    RelationshipFilter,
    RelationshipUpdate,
    SubjectFilter,
    SubjectReference,
    WriteRelationshipsRequest,
    ZedToken,
)
from authzed.api.v1.permission_service_pb2 import LOOKUP_PERMISSIONSHIP_HAS_PERMISSION
from httpx import request
from renku_data_services.base_models.core import APIUser
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services import base_models
from renku_data_services.authz.models import Member, Role, Scope, Visibility
from renku_data_services.errors import errors
from renku_data_services.project.models import Project


@dataclass
class _AuthzChange:
    """Used to designate relationships to be created/updated/deleted and how those can be undone.

    Sending the apply and undo relationships to the database must always be the equivalent of
    a no-op.
    """

    apply: WriteRelationshipsRequest = field(default_factory=WriteRelationshipsRequest)
    undo: WriteRelationshipsRequest = field(default_factory=WriteRelationshipsRequest)


class _Relation(StrEnum):
    """Relations for Authzed."""

    owner: str = "owner"
    viewer: str = "viewer"
    editor: str = "editor"
    admin: str = "admin"
    project_platform: str = "project_platform"

    @classmethod
    def from_role(cls, role: Role):
        match role:
            case Role.OWNER:
                return cls.owner
            case Role.EDITOR:
                return cls.editor
            case Role.VIEWER:
                return cls.viewer
        raise errors.ProgrammingError(message=f"Cannot map role {role} to any authorization database relation")

    def to_role(self) -> Role:
        match self:
            case _Relation.owner:
                return Role.OWNER
            case _Relation.editor:
                return Role.EDITOR
            case _Relation.viewer:
                return Role.VIEWER
        raise errors.ProgrammingError(message=f"Cannot map relation {self} to any role")


class ResourceType(StrEnum):
    """All possible resources stored in Authzed."""

    project: str = "project"
    user: str = "user"
    anonymous_user: str = "anonymous_user"
    platform: str = "platform"


class ProjectAuthzOperation(StrEnum):
    """The type of project change that requires authorization database update."""

    create: str = "create"
    delete: str = "delete"
    edit: str = "edit"
    change_visibility: str = "change_visibilty"
    change_membership: str = "change_membership"


class _AuthzConverter:
    @staticmethod
    def project(id: str) -> ObjectReference:
        return ObjectReference(object_type=ResourceType.project.value, object_id=id)

    @staticmethod
    def user(id: str | None) -> ObjectReference:
        if not id:
            return _AuthzConverter.all_users()
        return ObjectReference(object_type=ResourceType.user.value, object_id=id)

    @staticmethod
    def platform() -> ObjectReference:
        return ObjectReference(object_type=ResourceType.platform.value, object_id="renku")

    @staticmethod
    def anonymous_users() -> ObjectReference:
        return ObjectReference(object_type=ResourceType.anonymous_user, object_id="*")

    @staticmethod
    def anonymous_user() -> ObjectReference:
        return ObjectReference(object_type=ResourceType.anonymous_user, object_id="anonymous")

    @staticmethod
    def all_users() -> ObjectReference:
        return ObjectReference(object_type=ResourceType.user, object_id="*")


def _project_id_not_none(f):
    @wraps(f)
    def _project_id_not_none(self, project: Project, *args, **kwargs):
        if project.id is None:
            raise errors.ProgrammingError(message="Cannot create authorization relationships for project without an ID")
        return f(self, project, *args, **kwargs)

    return _project_id_not_none


def _is_allowed_on_project(operation: Scope):
    """A decorator that checks if the operation on a project is allowed or not."""

    class _DecoratedFuncType(Protocol):
        def __call__(self: "Authz", user: base_models.APIUser, project: Project, *args, **kwargs): ...

    def decorator(f: _DecoratedFuncType):
        @wraps(f)
        def decorated_function(self: "Authz", user: base_models.APIUser, project: Project, *args, **kwargs):
            allowed, zed_token = self._has_permission(user, ResourceType.project, project.id, operation)
            if not allowed:
                raise errors.MissingResourceError(
                    message=f"The user with ID {user.id} cannot perform operation {operation} on project "
                    f"with ID {project.id} or the project does not exist."
                )
            return f(self, user, project, *args, **kwargs, zed_token=zed_token)

        return decorated_function

    return decorator


def _is_allowed(operation: Scope):
    """A decorator that checks if the operation on a resource is allowed or not."""

    class _DecoratedFuncType(Protocol):
        def __call__(
            self: "Authz", user: base_models.APIUser, resource_type: ResourceType, resource_id: str, *args, **kwargs
        ): ...

    def decorator(f: _DecoratedFuncType):
        @wraps(f)
        def decorated_function(
            self: "Authz", user: base_models.APIUser, resource_type: ResourceType, resource_id: str, *args, **kwargs
        ):
            allowed, zed_token = self._has_permission(user, resource_type, resource_id, operation)
            if not allowed:
                raise errors.MissingResourceError(
                    message=f"The user with ID {user.id} cannot perform operation {operation} on {resource_type.value} "
                    f"with ID {resource_id} or the resource does not exist."
                )
            return f(self, user, resource_type, resource_id, *args, **kwargs, zed_token=zed_token)

        return decorated_function

    return decorator


@dataclass
class Authz:
    """Authorization decisions and updates."""

    client: Client
    _platform: ClassVar[ObjectReference] = field(default=_AuthzConverter.platform())

    def _to_object(self, resource_type: ResourceType, resource_id: str | int) -> ObjectReference:
        match (resource_type, resource_id):
            case (ResourceType.project, sid) if isinstance(sid, str):
                return _AuthzConverter.project(sid)
            case (ResourceType.user, sid) if isinstance(sid, str) or sid is None:
                return _AuthzConverter.user(sid)
            case (ResourceType.anonymous_user, _):
                return _AuthzConverter.anonymous_users()
        raise errors.ProgrammingError(
            message=f"Unexpected or uknnown resource type when checking permissions {resource_type}"
        )

    def _has_permission(
        self, user: base_models.APIUser, resource_type: ResourceType, resource_id: str, scope: Scope
    ) -> tuple[bool, ZedToken]:
        """Checks whether the provided user has a specific permission on the specific resource."""
        res = self._to_object(resource_type, resource_id)
        sub = SubjectReference(
            object=self._to_object(ResourceType.user, user.id) if user.id else _AuthzConverter.anonymous_user()
        )
        response: CheckPermissionResponse = self.client.CheckPermission(
            CheckPermissionRequest(
                consistency=Consistency(fully_consistent=True), resource=res, subject=sub, permission=scope.value
            )
        )
        return response.permissionship == CheckPermissionResponse.PERMISSIONSHIP_HAS_PERMISSION, response.checked_at

    def has_permission(
        self, user: base_models.APIUser, resource_type: ResourceType, resource_id: str, scope: Scope
    ) -> bool:
        """Checks whether the provided user has a specific permission on the specific resource."""
        res, _ = self._has_permission(user, resource_type, resource_id, scope)
        return res

    def resources_with_permission(
        self, requested_by: base_models.APIUser, user_id: str, resource_type: ResourceType, scope: Scope
    ) -> list[str]:
        """Get all the resource IDs (for a specific resource kind) that a specific user has access to.

        The person requesting the information can be the user or someone else. I.e. the admin can request
        what are the resources that a user has access to.
        """
        if not requested_by.is_admin and requested_by.id != user_id:
            raise errors.Unauthorized(
                message=f"User with ID {requested_by.id} cannot check the permissions of another user with ID {user_id}"
            )
        sub = SubjectReference(
            object=self._to_object(ResourceType.user, user_id) if user_id else _AuthzConverter.anonymous_user()
        )
        ids: list[str] = []
        responses: Iterator[LookupResourcesResponse] = self.client.LookupResources(
            LookupResourcesRequest(
                consistency=Consistency(fully_consistent=True),
                resource_object_type=resource_type.value,
                permission=scope.value,
                subject=sub,
            )
        )
        for response in responses:
            if response.permissionship == LOOKUP_PERMISSIONSHIP_HAS_PERMISSION:
                ids.append(response.resource_object_id)
        return ids

    @_is_allowed(Scope.READ)  # The scope on the resource that allows the user to perform this check in the first place
    def users_with_permission(
        self,
        user: base_models.APIUser,
        resource_type: ResourceType,
        resource_id: str,
        scope: Scope,  # The scope that the users should be allowed to exercise on the resource
        zed_token: ZedToken | None = None,
    ) -> list[str]:
        """Get all user IDs that have a specific permission on a specific reosurce."""
        res = self._to_object(resource_type, resource_id)
        ids: list[str] = []
        responses: Iterator[LookupSubjectsResponse] = self.client.LookupSubjects(
            LookupSubjectsRequest(
                consistency=Consistency(at_least_as_fresh=zed_token),
                resource=res,
                permission=scope.value,
                subject_object_type=ResourceType.user.value,
            )
        )
        for response in responses:
            if response.permissionship == LOOKUP_PERMISSIONSHIP_HAS_PERMISSION:
                ids.append(response.subject.subject_object_id)
        return ids

    @_is_allowed(Scope.READ)
    def members(
        self,
        user: base_models.APIUser,
        resource_type: ResourceType,
        resource_id: str,
        role: Role | None = None,
        zed_token: ZedToken | None = None,
    ) -> list[Member]:
        """Get all users that are members of a resource, if role is None then all roles are retrieved."""
        res = self._to_object(resource_type, resource_id)
        relation = _Relation.from_role(role)
        sub_filter = SubjectFilter(subject_type=ResourceType.user.value)
        rel_filter = RelationshipFilter(
            resource_type=resource_type,
            optional_resource_id=resource_id,
            optional_subject_filter=sub_filter,
        )
        if role:
            rel_filter = RelationshipFilter(
                resource_type=resource_type,
                optional_resource_id=resource_id,
                optional_relation=relation,
                optional_subject_filter=sub_filter,
            )
        responses: Iterator[ReadRelationshipsResponse] = self.client.ReadRelationships(
            ReadRelationshipsRequest(
                consistency=Consistency(at_least_as_fresh=zed_token),
                relationship_filter=rel_filter,
            )
        )
        members: list[Member] = []
        for response in responses:
            member_role = _Relation(response.relationship.relation).to_role()
            members.append(Member(user_id=response.relationship.subject.object.object_id, role=member_role))
        return members

    @staticmethod
    def project_change(op: ProjectAuthzOperation):
        """A decorator that updates the authorization database for different types of project operations."""

        class WithAuthz(Protocol):
            @property
            def authz(self) -> Authz: ...

        def decorator(f: Callable[..., Awaitable[Project]]):
            @wraps(f)
            async def decorated_function(
                db_repo: WithAuthz, session: AsyncSession, user: base_models.APIUser, *args, **kwargs
            ):
                # NOTE: db_repo is the "self" of the project postgres DB repository method that this function decorates.
                # I did not call it "self" here to avoid confusion with the self of the Authz class,
                # even though this is a static method.
                if not session.in_transaction():
                    raise errors.ProgrammingError(
                        message="Updating the project authorization database without a postgress transaction "
                        "is not allowed",
                    )
                try:
                    project = await f(db_repo, session, user, *args, **kwargs)
                    authz_change = _AuthzChange()
                    match op:
                        case ProjectAuthzOperation.create:
                            authz_change = db_repo.authz._add_project(project)
                        case ProjectAuthzOperation.delete:
                            authz_change = db_repo.authz._remove_project(user, project)
                        case ProjectAuthzOperation.change_visibility:
                            authz_change = db_repo.authz._update_project_visibility(user, project)
                        case _:
                            raise errors.ProgrammingError(
                                message=f"Encountered an unkonwn project authorization operation {op} "
                                f"when updating the project database for project with ID {project.id}",
                            )
                    db_repo.authz.client.WriteRelationships(authz_change.apply)
                    return project
                except Exception as err:
                    db_repo.authz.client.WriteRelationships(authz_change.undo)
                    raise err

            return decorated_function

        return decorator

    @_project_id_not_none
    def _add_project(self, project: Project) -> _AuthzChange:
        """Create the new project and associated resources and relations in the DB."""
        creator = SubjectReference(object=_AuthzConverter.user(project.created_by))
        project_res = _AuthzConverter.project(project.id)  # type: ignore[arg-type]
        creator_is_owner = Relationship(resource=project_res, relation=_Relation.owner.value, subject=creator)
        all_users = SubjectReference(object=_AuthzConverter.all_users())
        all_anon_users = SubjectReference(object=_AuthzConverter.anonymous_users())
        project_in_platform = Relationship(
            resource=project_res,
            relation=_Relation.project_platform.value,
            subject=SubjectReference(object=self._platform),
        )
        relationships = [creator_is_owner, project_in_platform]
        if project.visibility == Visibility.PUBLIC:
            all_users_are_viewers = Relationship(
                resource=project_res,
                relation=_Relation.viewer.value,
                subject=all_users,
            )
            all_anon_users_are_viewers = Relationship(
                resource=project_res,
                relation=_Relation.viewer.value,
                subject=all_anon_users,
            )
            relationships.extend([all_users_are_viewers, all_anon_users_are_viewers])
        apply = WriteRelationshipsRequest(
            updates=[
                RelationshipUpdate(operation=RelationshipUpdate.OPERATION_TOUCH, relationship=i) for i in relationships
            ]
        )
        undo = WriteRelationshipsRequest(
            updates=[
                RelationshipUpdate(operation=RelationshipUpdate.OPERATION_DELETE, relationship=i) for i in relationships
            ]
        )
        return _AuthzChange(apply=apply, undo=undo)

    @_project_id_not_none
    @_is_allowed_on_project(Scope.DELETE)
    def _remove_project(self, user: base_models.APIUser, project: Project, zed_token: ZedToken) -> _AuthzChange:
        """Remove the relationships associated with the project."""
        rel_filter = RelationshipFilter(resource_type=ResourceType.project.value, optional_resource_id=project.id)
        responses: Iterator[ReadRelationshipsResponse] = self.client.ReadRelationships(
            ReadRelationshipsRequest(
                consistency=Consistency(at_least_as_fresh=zed_token), relationship_filter=rel_filter
            )
        )
        rels: list[Relationship] = []
        for response in responses:
            rels.append(response.relationship)
        apply = WriteRelationshipsRequest(
            updates=[RelationshipUpdate(operation=RelationshipUpdate.OPERATION_DELETE, relationship=i) for i in rels]
        )
        undo = WriteRelationshipsRequest(
            updates=[RelationshipUpdate(operation=RelationshipUpdate.OPERATION_TOUCH, relationship=i) for i in rels]
        )
        return _AuthzChange(apply=apply, undo=undo)

    @_project_id_not_none
    @_is_allowed_on_project(Scope.DELETE)  # NOTE changing visibility is the same access level as removal
    def _update_project_visibility(
        self, user: base_models.APIUser, project: Project, zed_token: ZedToken
    ) -> _AuthzChange:
        """Update the visibility of the project in the authorization database."""
        project_res = _AuthzConverter.project(project.id)  # type: ignore[arg-type]
        all_users_sub = SubjectReference(object=_AuthzConverter.all_users())
        anon_users_sub = SubjectReference(object=_AuthzConverter.anonymous_users())
        all_users_are_viewers = Relationship(
            resource=project_res,
            relation=_Relation.viewer.value,
            subject=all_users_sub,
        )
        anon_users_are_viewers = Relationship(
            resource=project_res,
            relation=_Relation.viewer.value,
            subject=anon_users_sub,
        )
        make_public = WriteRelationshipsRequest(
            updates=[
                RelationshipUpdate(operation=RelationshipUpdate.OPERATION_TOUCH, relationship=all_users_are_viewers),
                RelationshipUpdate(operation=RelationshipUpdate.OPERATION_TOUCH, relationship=anon_users_are_viewers),
            ]
        )
        make_private = WriteRelationshipsRequest(
            updates=[
                RelationshipUpdate(operation=RelationshipUpdate.OPERATION_DELETE, relationship=all_users_are_viewers),
                RelationshipUpdate(operation=RelationshipUpdate.OPERATION_DELETE, relationship=anon_users_are_viewers),
            ]
        )
        rel_filter = RelationshipFilter(
            resource_type=ResourceType.project.value,
            optional_resource_id=project.id,
            optional_subject_filter=SubjectFilter(
                subject_type=ResourceType.user.value, optional_subject_id=all_users_sub.object.object_id
            ),
        )
        current_relation_users: ReadRelationshipsResponse = next(
            self.client.ReadRelationships(ReadRelationshipsRequest(relationship_filter=rel_filter)), None
        )
        rel_filter = RelationshipFilter(
            resource_type=ResourceType.project.value,
            optional_resource_id=project.id,
            optional_subject_filter=SubjectFilter(
                subject_type=ResourceType.anonymous_user.value,
                optional_subject_id=anon_users_sub.object.object_id,
            ),
        )
        current_relation_anon_users: ReadRelationshipsResponse = next(
            self.client.ReadRelationships(
                ReadRelationshipsRequest(
                    consistency=Consistency(at_least_as_fresh=zed_token), relationship_filter=rel_filter
                )
            ),
            None,
        )
        project_is_public_for_users = (
            current_relation_users is not None
            and current_relation_users.relationship.subject.object.object_type == ResourceType.user.value
            and current_relation_users.relationship.subject.object.object_id == all_users_sub.object.object_id
        )
        project_is_public_for_anon_users = (
            current_relation_anon_users is not None
            and current_relation_anon_users.relationship.subject.object.object_type == ResourceType.anonymous_user.value
            and current_relation_anon_users.relationship.subject.object.object_id == anon_users_sub.object.object_id,
        )
        match project.visibility:
            case Visibility.PUBLIC:
                if project_is_public_for_users and project_is_public_for_anon_users:
                    return _AuthzChange(apply=WriteRelationshipsRequest(), undo=WriteRelationshipsRequest())
                return _AuthzChange(apply=make_public, undo=make_private)
            case Visibility.PRIVATE:
                if not project_is_public_for_users and not project_is_public_for_anon_users:
                    return _AuthzChange(apply=WriteRelationshipsRequest(), undo=WriteRelationshipsRequest())
                return _AuthzChange(apply=make_private, undo=make_public)
        raise errors.ProgrammingError(
            message=f"Encountered unknown project visibility {project.visibility} when trying to "
            f"update permissions for visibility change for project with ID {project.id}",
        )

    @_is_allowed_on_project(Scope.CHANGE_MEMBERSHIP)
    def upsert_project_members(
        self, user: base_models.APIUser, project: Project, members: list[Member], zed_token: ZedToken
    ) -> list[Member]:
        """Updates the project members or inserts them if they do not exist.

        Returns the list that was updated/inserted.
        """
        project_res = _AuthzConverter.project(project.id)
        add_members: list[RelationshipUpdate] = []
        undo: list[RelationshipUpdate] = []
        for member in members:
            rel = Relationship(
                resource=project_res,
                relation=_Relation.from_role(member.role).value,
                subject=SubjectReference(object=_AuthzConverter.user(member.user_id)),
            )
            existing_rel_filter = RelationshipFilter(
                resource_type=ResourceType.project,
                optional_resource_id=project.id,
                optional_subject_filter=SubjectFilter(
                    subject_type=ResourceType.user, optional_subject_id=member.user_id
                ),
            )
            existing_rels: list[ReadRelationshipsResponse] = list(
                self.client.ReadRelationships(
                    ReadRelationshipsRequest(
                        consistency=Consistency(at_least_as_fresh=zed_token), relationship_filter=existing_rel_filter
                    )
                )
            )
            # The new relationship is added if all goes well and deleted if we have to undo
            add_members.extend(
                [
                    RelationshipUpdate(operation=RelationshipUpdate.OPERATION_TOUCH, relationship=rel),
                ]
            )
            undo.append(
                RelationshipUpdate(operation=RelationshipUpdate.OPERATION_DELETE, relationship=rel),
            )
            # The existing relationships should be deleted if all goes well and added back in if we have to undo
            if len(existing_rels) > 0:
                for existing_rel in existing_rels:
                    add_members.append(
                        RelationshipUpdate(
                            operation=RelationshipUpdate.OPERATION_DELETE, relationship=existing_rel.relationship
                        ),
                    )
                    undo.append(
                        RelationshipUpdate(
                            operation=RelationshipUpdate.OPERATION_TOUCH, relationship=existing_rel.relationship
                        ),
                    )
        change = _AuthzChange(
            apply=WriteRelationshipsRequest(updates=add_members), undo=WriteRelationshipsRequest(updates=undo)
        )
        try:
            self.client.WriteRelationships(change.apply)
        except Exception as err:
            self.client.WriteRelationships(change.undo)
            raise err
        return members

    @_is_allowed_on_project(Scope.CHANGE_MEMBERSHIP)
    def remove_project_members(
        self, user: base_models.APIUser, project: Project, members: list[Member], zed_token: ZedToken
    ) -> list[Member]:
        """Remove the specific members from the project, then return the list of members that were removed."""
        project_res = _AuthzConverter.project(project.id)  # type: ignore[arg-type]
        add_members: list[RelationshipUpdate] = []
        remove_members: list[RelationshipUpdate] = []
        for member in members:
            existing_rel_filter = RelationshipFilter(
                resource_type=ResourceType.project,
                optional_resource_id=project.id,
                optional_subject_filter=SubjectFilter(
                    subject_type=ResourceType.user, optional_subject_id=member.user_id
                ),
            )
            existing_rels: Iterator[ReadRelationshipsResponse] = self.client.ReadRelationships(
                ReadRelationshipsRequest(
                    consistency=Consistency(at_least_as_fresh=zed_token), relationship_filter=existing_rel_filter
                )
            )
            # NOTE: We have to make sure that when we undo we only put back relationships that existed already.
            # Blidnly putting back all removed relationship may result in adding things that weren't there before.
            for existing_rel in existing_rels:
                add_members.append(
                    RelationshipUpdate(
                        operation=RelationshipUpdate.OPERATION_TOUCH, relationship=existing_rel.relationship
                    )
                )
            rel = Relationship(
                resource=project_res,
                relation=_Relation.from_role(member.role).value,
                subject=SubjectReference(_AuthzConverter.user(member.user_id)),
            )
            remove_members.append(RelationshipUpdate(operation=RelationshipUpdate.OPERATION_DELETE, relationship=rel))
        change = _AuthzChange(
            apply=WriteRelationshipsRequest(updates=remove_members), undo=WriteRelationshipsRequest(updates=add_members)
        )
        try:
            self.client.WriteRelationships(change.apply)
        except Exception as err:
            self.client.WriteRelationships(change.undo)
            raise err
        return members
