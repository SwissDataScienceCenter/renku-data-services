"""Projects authorization adapter."""

import asyncio
from collections.abc import AsyncIterable, Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from functools import wraps
from typing import ClassVar, Concatenate, ParamSpec, Protocol, TypeVar, cast

from authzed.api.v1 import AsyncClient
from authzed.api.v1.core_pb2 import ObjectReference, Relationship, RelationshipUpdate, SubjectReference, ZedToken
from authzed.api.v1.permission_service_pb2 import (
    LOOKUP_PERMISSIONSHIP_HAS_PERMISSION,
    CheckPermissionRequest,
    CheckPermissionResponse,
    Consistency,
    LookupResourcesRequest,
    LookupResourcesResponse,
    LookupSubjectsRequest,
    LookupSubjectsResponse,
    ReadRelationshipsRequest,
    ReadRelationshipsResponse,
    RelationshipFilter,
    SubjectFilter,
    WriteRelationshipsRequest,
)
from sanic.log import logger
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from renku_data_services import base_models
from renku_data_services.authz.config import AuthzConfig
from renku_data_services.authz.models import Change, Member, MembershipChange, Role, Scope, Visibility
from renku_data_services.base_models.core import InternalServiceAdmin
from renku_data_services.errors import errors
from renku_data_services.namespace.models import Group, GroupUpdate, Namespace, NamespaceKind, NamespaceUpdate
from renku_data_services.project.models import Project, ProjectUpdate
from renku_data_services.users.models import UserInfo, UserInfoUpdate

_P = ParamSpec("_P")


class WithAuthz(Protocol):
    """Protocol for a class that has a authorization database client as property."""

    @property
    def authz(self) -> "Authz":
        """Returns the authorization database client."""
        ...


_AuthzChangeFuncResult = TypeVar(
    "_AuthzChangeFuncResult",
    bound=Project | ProjectUpdate | Group | UserInfoUpdate | list[UserInfo] | None,
)
_T = TypeVar("_T")
_WithAuthz = TypeVar("_WithAuthz", bound=WithAuthz)


@dataclass
class _AuthzChange:
    """Used to designate relationships to be created/updated/deleted and how those can be undone.

    Sending the apply and undo relationships to the database must always be the equivalent of
    a no-op.
    """

    apply: WriteRelationshipsRequest = field(default_factory=WriteRelationshipsRequest)
    undo: WriteRelationshipsRequest = field(default_factory=WriteRelationshipsRequest)

    def extend(self, other: "_AuthzChange") -> None:
        self.apply.updates.extend(other.apply.updates)
        self.apply.optional_preconditions.extend(other.apply.optional_preconditions)
        self.undo.updates.extend(other.undo.updates)
        self.undo.optional_preconditions.extend(other.undo.optional_preconditions)


class _Relation(StrEnum):
    """Relations for Authzed."""

    owner: str = "owner"
    editor: str = "editor"
    viewer: str = "viewer"
    public_viewer: str = "public_viewer"
    admin: str = "admin"
    project_platform: str = "project_platform"
    group_platform: str = "group_platform"
    user_namespace_platform: str = "user_namespace_platform"
    project_namespace: str = "project_namespace"

    @classmethod
    def from_role(cls, role: Role) -> "_Relation":
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
    group: str = "group"
    user_namespace: str = "user_namespace"


class AuthzOperation(StrEnum):
    """The type of change that requires authorization database update."""

    create: str = "create"
    delete: str = "delete"
    update: str = "update"
    update_or_insert: str = "update_or_insert"
    insert_many: str = "insert_many"


class _AuthzConverter:
    @staticmethod
    def project(id: ULID) -> ObjectReference:
        return ObjectReference(object_type=ResourceType.project.value, object_id=str(id))

    @staticmethod
    def user(id: str | None) -> ObjectReference:
        if not id:
            return _AuthzConverter.all_users()
        return ObjectReference(object_type=ResourceType.user.value, object_id=id)

    @staticmethod
    def user_subject(id: str | None) -> SubjectReference:
        return SubjectReference(object=_AuthzConverter.user(id))

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

    @staticmethod
    def group(id: ULID) -> ObjectReference:
        return ObjectReference(object_type=ResourceType.group, object_id=str(id))

    @staticmethod
    def user_namespace(id: ULID) -> ObjectReference:
        return ObjectReference(object_type=ResourceType.user_namespace, object_id=str(id))

    @staticmethod
    def to_object(resource_type: ResourceType, resource_id: str | ULID | int) -> ObjectReference:
        match (resource_type, resource_id):
            case (ResourceType.project, sid) if isinstance(sid, ULID):
                return _AuthzConverter.project(sid)
            case (ResourceType.user, sid) if isinstance(sid, str) or sid is None:
                return _AuthzConverter.user(sid)
            case (ResourceType.anonymous_user, _):
                return _AuthzConverter.anonymous_users()
            case (ResourceType.user_namespace, rid) if isinstance(rid, ULID):
                return _AuthzConverter.user_namespace(rid)
            case (ResourceType.group, rid) if isinstance(rid, ULID):
                return _AuthzConverter.group(rid)
        raise errors.ProgrammingError(
            message=f"Unexpected or unknown resource type when checking permissions {resource_type}"
        )


def _is_allowed_on_resource(
    operation: Scope, resource_type: ResourceType
) -> Callable[
    [Callable[Concatenate["Authz", base_models.APIUser, _P], Awaitable[_T]]],
    Callable[Concatenate["Authz", base_models.APIUser, _P], Awaitable[_T]],
]:
    """A decorator that checks if the operation on a specific resource type is allowed or not."""

    def decorator(
        f: Callable[Concatenate["Authz", base_models.APIUser, _P], Awaitable[_T]],
    ) -> Callable[Concatenate["Authz", base_models.APIUser, _P], Awaitable[_T]]:
        @wraps(f)
        async def decorated_function(
            self: "Authz", user: base_models.APIUser, *args: _P.args, **kwargs: _P.kwargs
        ) -> _T:
            if isinstance(user, base_models.InternalServiceAdmin):
                return await f(self, user, *args, **kwargs)
            if not isinstance(user, base_models.APIUser):
                raise errors.ProgrammingError(
                    message="The decorator for checking permissions for authorization database operations "
                    "needs to access the user in the decorated function keyword arguments but it did not find it"
                )
            if len(args) == 0:
                raise errors.ProgrammingError(
                    message="The authorization decorator needs to have at least one positional argument after 'user'"
                )
            potential_resource = args[0]
            resource: Project | Group | Namespace | None = None
            match resource_type:
                case ResourceType.project if isinstance(potential_resource, Project):
                    resource = potential_resource
                case ResourceType.group if isinstance(potential_resource, Group):
                    resource = potential_resource
                case ResourceType.user_namespace if isinstance(potential_resource, Namespace):
                    resource = potential_resource
                case _:
                    raise errors.ProgrammingError(
                        message="The decorator for checking permissions for authorization database operations "
                        "failed to find the expected positional argument in the decorated function "
                        f"for the {resource_type} resource, it found {type(resource)}"
                    )
            allowed, zed_token = await self._has_permission(user, resource_type, resource.id, operation)
            if not allowed:
                raise errors.MissingResourceError(
                    message=f"The user with ID {user.id} cannot perform operation {operation} "
                    f"on resource {resource_type} with ID {resource.id} or the resource does not exist."
                )
            kwargs["zed_token"] = zed_token
            return await f(self, user, *args, **kwargs)

        return decorated_function

    return decorator


_ID = TypeVar("_ID", str, ULID)


def _is_allowed(
    operation: Scope,
) -> Callable[
    [Callable[Concatenate["Authz", base_models.APIUser, ResourceType, _ID, _P], Awaitable[_T]]],
    Callable[Concatenate["Authz", base_models.APIUser, ResourceType, _ID, _P], Awaitable[_T]],
]:
    """A decorator that checks if the operation on a resource is allowed or not."""

    def decorator(
        f: Callable[Concatenate["Authz", base_models.APIUser, ResourceType, _ID, _P], Awaitable[_T]],
    ) -> Callable[Concatenate["Authz", base_models.APIUser, ResourceType, _ID, _P], Awaitable[_T]]:
        @wraps(f)
        async def decorated_function(
            self: "Authz",
            user: base_models.APIUser,
            resource_type: ResourceType,
            resource_id: _ID,
            *args: _P.args,
            **kwargs: _P.kwargs,
        ) -> _T:
            if isinstance(user, base_models.InternalServiceAdmin):
                return await f(self, user, resource_type, resource_id, *args, **kwargs)
            allowed, zed_token = await self._has_permission(user, resource_type, resource_id, operation)
            if not allowed:
                raise errors.MissingResourceError(
                    message=f"The user with ID {user.id} cannot perform operation {operation} on {resource_type.value} "
                    f"with ID {resource_id} or the resource does not exist."
                )
            kwargs["zed_token"] = zed_token
            return await f(self, user, resource_type, resource_id, *args, **kwargs)

        return decorated_function

    return decorator


@dataclass
class Authz:
    """Authorization decisions and updates."""

    authz_config: AuthzConfig
    _platform: ClassVar[ObjectReference] = field(default=_AuthzConverter.platform())
    _client: AsyncClient | None = field(default=None, init=False)

    @property
    def client(self) -> AsyncClient:
        """The authzed DB asynchronous client."""
        if not self._client:
            self._client = self.authz_config.authz_async_client()
        return self._client

    async def _has_permission(
        self, user: base_models.APIUser, resource_type: ResourceType, resource_id: str | ULID | None, scope: Scope
    ) -> tuple[bool, ZedToken | None]:
        """Checks whether the provided user has a specific permission on the specific resource."""
        if not resource_id:
            raise errors.ProgrammingError(
                message=f"Cannot check permissions on a resource of type {resource_type} with missing resource ID."
            )
        if isinstance(user, InternalServiceAdmin):
            return True, None
        res = _AuthzConverter.to_object(resource_type, resource_id)
        sub = SubjectReference(
            object=(
                _AuthzConverter.to_object(ResourceType.user, user.id) if user.id else _AuthzConverter.anonymous_user()
            )
        )
        response: CheckPermissionResponse = await self.client.CheckPermission(
            CheckPermissionRequest(
                consistency=Consistency(fully_consistent=True), resource=res, subject=sub, permission=scope.value
            )
        )
        return response.permissionship == CheckPermissionResponse.PERMISSIONSHIP_HAS_PERMISSION, response.checked_at

    async def has_permission(
        self, user: base_models.APIUser, resource_type: ResourceType, resource_id: str | ULID, scope: Scope
    ) -> bool:
        """Checks whether the provided user has a specific permission on the specific resource."""
        res, _ = await self._has_permission(user, resource_type, resource_id, scope)
        return res

    async def resources_with_permission(
        self, requested_by: base_models.APIUser, user_id: str | None, resource_type: ResourceType, scope: Scope
    ) -> list[str]:
        """Get all the resource IDs (for a specific resource kind) that a specific user has access to.

        The person requesting the information can be the user or someone else. I.e. the admin can request
        what are the resources that a user has access to.
        """
        if not requested_by.is_admin and requested_by.id != user_id:
            raise errors.ForbiddenError(
                message=f"User with ID {requested_by.id} cannot check the permissions of another user with ID {user_id}"
            )
        sub = SubjectReference(
            object=(
                _AuthzConverter.to_object(ResourceType.user, user_id) if user_id else _AuthzConverter.anonymous_user()
            )
        )
        ids: list[str] = []
        responses: AsyncIterable[LookupResourcesResponse] = self.client.LookupResources(
            LookupResourcesRequest(
                consistency=Consistency(fully_consistent=True),
                resource_object_type=resource_type.value,
                permission=scope.value,
                subject=sub,
            )
        )
        async for response in responses:
            if response.permissionship == LOOKUP_PERMISSIONSHIP_HAS_PERMISSION:
                ids.append(response.resource_object_id)
        return ids

    @_is_allowed(Scope.READ)  # The scope on the resource that allows the user to perform this check in the first place
    async def users_with_permission(
        self,
        user: base_models.APIUser,
        resource_type: ResourceType,
        resource_id: str,
        scope: Scope,  # The scope that the users should be allowed to exercise on the resource
        *,
        zed_token: ZedToken | None = None,
    ) -> list[str]:
        """Get all user IDs that have a specific permission on a specific resource."""
        consistency = Consistency(at_least_as_fresh=zed_token) if zed_token else Consistency(fully_consistent=True)
        res = _AuthzConverter.to_object(resource_type, resource_id)
        ids: list[str] = []
        responses: AsyncIterable[LookupSubjectsResponse] = self.client.LookupSubjects(
            LookupSubjectsRequest(
                consistency=consistency,
                resource=res,
                permission=scope.value,
                subject_object_type=ResourceType.user.value,
            )
        )
        async for response in responses:
            if response.permissionship == LOOKUP_PERMISSIONSHIP_HAS_PERMISSION:
                ids.append(response.subject.subject_object_id)
        return ids

    @_is_allowed(Scope.READ)
    async def members(
        self,
        user: base_models.APIUser,
        resource_type: ResourceType,
        resource_id: ULID,
        role: Role | None = None,
        *,
        zed_token: ZedToken | None = None,
    ) -> list[Member]:
        """Get all users that are members of a resource, if role is None then all roles are retrieved."""
        resource_id_str = str(resource_id)
        consistency = Consistency(at_least_as_fresh=zed_token) if zed_token else Consistency(fully_consistent=True)
        sub_filter = SubjectFilter(subject_type=ResourceType.user.value)
        rel_filter = RelationshipFilter(
            resource_type=resource_type,
            optional_resource_id=resource_id_str,
            optional_subject_filter=sub_filter,
        )
        if role:
            relation = _Relation.from_role(role)
            rel_filter = RelationshipFilter(
                resource_type=resource_type,
                optional_resource_id=resource_id_str,
                optional_relation=relation,
                optional_subject_filter=sub_filter,
            )
        responses: AsyncIterable[ReadRelationshipsResponse] = self.client.ReadRelationships(
            ReadRelationshipsRequest(
                consistency=consistency,
                relationship_filter=rel_filter,
            )
        )
        members: list[Member] = []
        async for response in responses:
            # Skip "public_viewer" relationships
            if response.relationship.relation == _Relation.public_viewer.value:
                continue
            member_role = _Relation(response.relationship.relation).to_role()
            members.append(
                Member(
                    user_id=response.relationship.subject.object.object_id, role=member_role, resource_id=resource_id
                )
            )
        return members

    @staticmethod
    def authz_change(
        op: AuthzOperation, resource: ResourceType
    ) -> Callable[
        [Callable[Concatenate[_WithAuthz, _P], Awaitable[_AuthzChangeFuncResult]]],
        Callable[Concatenate[_WithAuthz, _P], Awaitable[_AuthzChangeFuncResult]],
    ]:
        """A decorator that updates the authorization database for different types of operations."""

        def _extract_user_from_args(*args: _P.args, **kwargs: _P.kwargs) -> base_models.APIUser:
            if len(args) == 0:
                user_kwarg = kwargs.get("user")
                requested_by_kwarg = kwargs.get("requested_by")
                if isinstance(user_kwarg, base_models.APIUser) and isinstance(requested_by_kwarg, base_models.APIUser):
                    raise errors.ProgrammingError(
                        message="The decorator for authorization database changes found two APIUser parameters in the "
                        "'user' and 'requested_by' keyword arguments but expected only one of them to be present."
                    )
                potential_user = user_kwarg if isinstance(user_kwarg, base_models.APIUser) else requested_by_kwarg
            else:
                potential_user = args[0]
            if not isinstance(potential_user, base_models.APIUser):
                raise errors.ProgrammingError(
                    message="The decorator for authorization database changes could not find APIUser in the function "
                    f"arguments, the type of the argument that was found is {type(potential_user)}."
                )
            return potential_user

        async def _get_authz_change(
            db_repo: _WithAuthz,
            operation: AuthzOperation,
            resource: ResourceType,
            result: _AuthzChangeFuncResult,
            *func_args: _P.args,
            **func_kwargs: _P.kwargs,
        ) -> _AuthzChange:
            authz_change = _AuthzChange()
            match operation, resource:
                case AuthzOperation.create, ResourceType.project if isinstance(result, Project):
                    authz_change = db_repo.authz._add_project(result)
                case AuthzOperation.delete, ResourceType.project if isinstance(result, Project):
                    user = _extract_user_from_args(*func_args, **func_kwargs)
                    authz_change = await db_repo.authz._remove_entity(user, result)
                case AuthzOperation.delete, ResourceType.project if result is None:
                    # NOTE: This means that the project does not exist in the first place so nothing was deleted
                    pass
                case AuthzOperation.update, ResourceType.project if isinstance(result, ProjectUpdate):
                    authz_change = _AuthzChange()
                    if result.old.visibility != result.new.visibility:
                        user = _extract_user_from_args(*func_args, **func_kwargs)
                        authz_change.extend(await db_repo.authz._update_project_visibility(user, result.new))
                    if result.old.namespace.id != result.new.namespace.id:
                        user = _extract_user_from_args(*func_args, **func_kwargs)
                        authz_change.extend(await db_repo.authz._update_project_namespace(user, result.new))
                case AuthzOperation.create, ResourceType.group if isinstance(result, Group):
                    authz_change = db_repo.authz._add_group(result)
                case AuthzOperation.delete, ResourceType.group if isinstance(result, Group):
                    user = _extract_user_from_args(*func_args, **func_kwargs)
                    authz_change = await db_repo.authz._remove_entity(user, result)
                case AuthzOperation.delete, ResourceType.group if result is None:
                    # NOTE: This means that the group does not exist in the first place so nothing was deleted
                    pass
                case AuthzOperation.update_or_insert, ResourceType.user if isinstance(result, UserInfoUpdate):
                    if result.old is None:
                        authz_change = db_repo.authz._add_user_namespace(result.new.namespace)
                case AuthzOperation.insert_many, ResourceType.user_namespace if isinstance(result, list):
                    for res in result:
                        if not isinstance(res, UserInfo):
                            raise errors.ProgrammingError(
                                message="Expected list of UserInfo when generating authorization "
                                f"database updates for inserting namespaces but found {type(res)}"
                            )
                        authz_change.extend(db_repo.authz._add_user_namespace(res.namespace))
                case _:
                    resource_id: str | ULID | None = "unknown"
                    if isinstance(result, (Project, Namespace, Group)):
                        resource_id = result.id
                    elif isinstance(result, (ProjectUpdate, NamespaceUpdate, GroupUpdate)):
                        resource_id = result.new.id
                    raise errors.ProgrammingError(
                        message=f"Encountered an unknown authorization operation {op} on resource {resource} "
                        f"with ID {resource_id} when updating the authorization database",
                    )
            return authz_change

        def decorator(
            f: Callable[Concatenate[_WithAuthz, _P], Awaitable[_AuthzChangeFuncResult]],
        ) -> Callable[Concatenate[_WithAuthz, _P], Awaitable[_AuthzChangeFuncResult]]:
            @wraps(f)
            async def decorated_function(
                db_repo: _WithAuthz, *args: _P.args, **kwargs: _P.kwargs
            ) -> _AuthzChangeFuncResult:
                # NOTE: db_repo is the "self" of the project postgres DB repository method that this function decorates.
                # I did not call it "self" here to avoid confusion with the self of the Authz class,
                # even though this is a static method.
                session = kwargs.get("session")
                if not isinstance(session, AsyncSession):
                    raise errors.ProgrammingError(
                        message="The authorization change decorator requires a DB session in the function "
                        "keyword arguments"
                    )
                if not session.in_transaction():
                    raise errors.ProgrammingError(
                        message="The authorization database decorator needs a session with an open transaction."
                    )

                authz_change = _AuthzChange()
                try:
                    # NOTE: Here we have to maintain the following order of operations:
                    # 1. Run decorated function
                    # 2. Write resources to the Authzed DB
                    # 3. Commit the open transaction
                    # 4. If something goes wrong abort the transaction and remove things from Authzed DB
                    # See https://authzed.com/docs/spicedb/concepts/relationships#writing-relationships
                    # If this order of operations is changed you can get a case where for a short period of time
                    # resources exists in the postgres DB without any authorization information in the Authzed DB.
                    result = await f(db_repo, *args, **kwargs)
                    authz_change = await _get_authz_change(db_repo, op, resource, result, *args, **kwargs)
                    await db_repo.authz.client.WriteRelationships(authz_change.apply)
                    await session.commit()
                    return result
                except Exception as err:
                    db_rollback_err = None
                    try:
                        # NOTE: If the rollback fails do not stop just continue to make sure the resource
                        # from the Authzed DB is also removed
                        await asyncio.shield(session.rollback())
                    except Exception as _db_rollback_err:
                        db_rollback_err = _db_rollback_err
                    await asyncio.shield(db_repo.authz.client.WriteRelationships(authz_change.undo))
                    if db_rollback_err:
                        raise db_rollback_err from err
                    raise err

            return decorated_function

        return decorator

    async def _remove_entity(
        self, user: base_models.APIUser, resource: UserInfo | Group | Namespace | Project
    ) -> _AuthzChange:
        resource_type: ResourceType
        match resource:
            case _ if isinstance(resource, UserInfo):
                resource_type = ResourceType.user
            case _ if isinstance(resource, Group):
                resource_type = ResourceType.group
            case _ if isinstance(resource, Namespace) and resource.kind == NamespaceKind.user:
                resource_type = ResourceType.user_namespace
            case _ if isinstance(resource, Namespace):
                raise errors.ProgrammingError(
                    message=f"Cannot handle deletetion of namespace {resource.id} of kind {resource.kind.value}."
                )
            case _ if isinstance(resource, Project):
                resource_type = ResourceType.project
            case _:
                raise errors.ProgrammingError(message="Cannot handle deletion of unknown resource.")
        resource_id = str(resource.id)

        @_is_allowed_on_resource(Scope.DELETE, resource_type)
        async def _remove_entity_wrapped(
            authz: Authz,
            user: base_models.APIUser,
            resource: UserInfo | Group | Namespace | Project,
            *,
            zed_token: ZedToken | None = None,
        ) -> _AuthzChange:
            consistency = Consistency(at_least_as_fresh=zed_token) if zed_token else Consistency(fully_consistent=True)
            rels: list[Relationship] = []
            # Get relations where the entity is the resource
            rel_filter = RelationshipFilter(resource_type=resource_type.value, optional_resource_id=resource_id)
            responses: AsyncIterable[ReadRelationshipsResponse] = authz.client.ReadRelationships(
                ReadRelationshipsRequest(consistency=consistency, relationship_filter=rel_filter)
            )
            async for response in responses:
                rels.append(response.relationship)
            # Get relations where the entity is the subject
            rel_filter = RelationshipFilter(
                optional_subject_filter=SubjectFilter(subject_type=resource_type, optional_subject_id=resource_id)
            )
            responses: AsyncIterable[ReadRelationshipsResponse] = authz.client.ReadRelationships(
                ReadRelationshipsRequest(consistency=consistency, relationship_filter=rel_filter)
            )
            async for response in responses:
                rels.append(response.relationship)
            apply = WriteRelationshipsRequest(
                updates=[
                    RelationshipUpdate(operation=RelationshipUpdate.OPERATION_DELETE, relationship=i) for i in rels
                ]
            )
            undo = WriteRelationshipsRequest(
                updates=[RelationshipUpdate(operation=RelationshipUpdate.OPERATION_TOUCH, relationship=i) for i in rels]
            )
            return _AuthzChange(apply=apply, undo=undo)

        return await _remove_entity_wrapped(self, user, resource)

    def _add_project(self, project: Project) -> _AuthzChange:
        """Create the new project and associated resources and relations in the DB."""
        creator = SubjectReference(object=_AuthzConverter.user(project.created_by))
        project_res = _AuthzConverter.project(project.id)
        creator_is_owner = Relationship(resource=project_res, relation=_Relation.owner.value, subject=creator)
        all_users = SubjectReference(object=_AuthzConverter.all_users())
        all_anon_users = SubjectReference(object=_AuthzConverter.anonymous_users())
        project_namespace = SubjectReference(
            object=(
                _AuthzConverter.user_namespace(project.namespace.id)
                if project.namespace.kind == NamespaceKind.user
                else _AuthzConverter.group(cast(ULID, project.namespace.underlying_resource_id))
            )
        )
        project_in_platform = Relationship(
            resource=project_res,
            relation=_Relation.project_platform.value,
            subject=SubjectReference(object=self._platform),
        )
        project_in_namespace = Relationship(
            resource=project_res,
            relation=_Relation.project_namespace,
            subject=project_namespace,
        )
        relationships = [creator_is_owner, project_in_platform, project_in_namespace]
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

    # NOTE changing visibility is the same access level as removal
    @_is_allowed_on_resource(Scope.DELETE, ResourceType.project)
    async def _update_project_visibility(
        self, user: base_models.APIUser, project: Project, *, zed_token: ZedToken | None = None
    ) -> _AuthzChange:
        """Update the visibility of the project in the authorization database."""
        project_id_str = str(project.id)
        consistency = Consistency(at_least_as_fresh=zed_token) if zed_token else Consistency(fully_consistent=True)
        project_res = _AuthzConverter.project(project.id)
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
            optional_resource_id=project_id_str,
            optional_subject_filter=SubjectFilter(
                subject_type=ResourceType.user.value, optional_subject_id=all_users_sub.object.object_id
            ),
        )
        current_relation_users: ReadRelationshipsResponse | None = await anext(
            aiter(self.client.ReadRelationships(ReadRelationshipsRequest(relationship_filter=rel_filter))), None
        )
        rel_filter = RelationshipFilter(
            resource_type=ResourceType.project.value,
            optional_resource_id=project_id_str,
            optional_subject_filter=SubjectFilter(
                subject_type=ResourceType.anonymous_user.value,
                optional_subject_id=anon_users_sub.object.object_id,
            ),
        )
        current_relation_anon_users: ReadRelationshipsResponse | None = await anext(
            aiter(
                self.client.ReadRelationships(
                    ReadRelationshipsRequest(consistency=consistency, relationship_filter=rel_filter)
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
        project_already_public = project_is_public_for_users and project_is_public_for_anon_users
        project_already_private = not project_already_public
        match project.visibility:
            case Visibility.PUBLIC:
                if project_already_public:
                    return _AuthzChange(apply=WriteRelationshipsRequest(), undo=WriteRelationshipsRequest())
                return _AuthzChange(apply=make_public, undo=make_private)
            case Visibility.PRIVATE:
                if project_already_private:
                    return _AuthzChange(apply=WriteRelationshipsRequest(), undo=WriteRelationshipsRequest())
                return _AuthzChange(apply=make_private, undo=make_public)
        raise errors.ProgrammingError(
            message=f"Encountered unknown project visibility {project.visibility} when trying to "
            f"make a visibility change for project with ID {project.id}",
        )

    # NOTE changing namespace is the same access level as removal
    @_is_allowed_on_resource(Scope.DELETE, ResourceType.project)
    async def _update_project_namespace(
        self, user: base_models.APIUser, project: Project, *, zed_token: ZedToken | None = None
    ) -> _AuthzChange:
        """Update the namespace/group of the project in the authorization database."""
        consistency = Consistency(at_least_as_fresh=zed_token) if zed_token else Consistency(fully_consistent=True)
        project_res = _AuthzConverter.project(project.id)
        project_namespace_filter = RelationshipFilter(
            resource_type=ResourceType.project.value,
            optional_resource_id=str(project.id),
            optional_relation=_Relation.project_namespace.value,
        )
        current_namespace: ReadRelationshipsResponse | None = await anext(
            aiter(
                self.client.ReadRelationships(
                    ReadRelationshipsRequest(relationship_filter=project_namespace_filter, consistency=consistency)
                )
            ),
            None,
        )
        if not current_namespace:
            raise errors.ProgrammingError(
                message=f"The project with ID {project.id} whose namespace is being updated "
                "does not currently have a namespace"
            )
        if current_namespace.relationship.subject.object.object_id == project.namespace.id:
            return _AuthzChange()
        new_namespace_sub = (
            SubjectReference(object=_AuthzConverter.group(project.namespace.id))
            if project.namespace.kind == NamespaceKind.group
            else SubjectReference(object=_AuthzConverter.user_namespace(project.namespace.id))
        )
        old_namespace_sub = (
            SubjectReference(
                object=_AuthzConverter.group(ULID.from_str(current_namespace.relationship.subject.object.object_id))
            )
            if current_namespace.relationship.subject.object.object_type == ResourceType.group.value
            else SubjectReference(
                object=_AuthzConverter.user_namespace(
                    ULID.from_str(current_namespace.relationship.subject.object.object_id)
                )
            )
        )
        new_namespace = Relationship(
            resource=project_res,
            relation=_Relation.project_namespace.value,
            subject=new_namespace_sub,
        )
        old_namespace = Relationship(
            resource=project_res,
            relation=_Relation.project_namespace.value,
            subject=old_namespace_sub,
        )
        apply_change = WriteRelationshipsRequest(
            updates=[
                RelationshipUpdate(operation=RelationshipUpdate.OPERATION_TOUCH, relationship=new_namespace),
            ]
        )
        undo_change = WriteRelationshipsRequest(
            updates=[
                RelationshipUpdate(operation=RelationshipUpdate.OPERATION_TOUCH, relationship=old_namespace),
            ]
        )
        return _AuthzChange(apply=apply_change, undo=undo_change)

    async def _get_resource_owners(
        self, resource_type: ResourceType, resource_id: str, consistency: Consistency
    ) -> list[ReadRelationshipsResponse]:
        existing_owners_filter = RelationshipFilter(
            resource_type=resource_type.value,
            optional_resource_id=resource_id,
            optional_subject_filter=SubjectFilter(subject_type=ResourceType.user),
            optional_relation=_Relation.owner.value,
        )
        return [
            i
            async for i in self.client.ReadRelationships(
                ReadRelationshipsRequest(
                    consistency=consistency,
                    relationship_filter=existing_owners_filter,
                )
            )
        ]

    @_is_allowed(Scope.CHANGE_MEMBERSHIP)
    async def upsert_project_members(
        self,
        user: base_models.APIUser,
        resource_type: ResourceType,
        resource_id: ULID,
        members: list[Member],
        *,
        zed_token: ZedToken | None = None,
    ) -> list[MembershipChange]:
        """Updates the project members or inserts them if they do not exist.

        Returns the list that was updated/inserted.
        """
        resource_id_str = str(resource_id)
        consistency = Consistency(at_least_as_fresh=zed_token) if zed_token else Consistency(fully_consistent=True)
        project_res = _AuthzConverter.project(resource_id)
        add_members: list[RelationshipUpdate] = []
        undo: list[RelationshipUpdate] = []
        output: list[MembershipChange] = []
        expected_user_roles = {_Relation.viewer.value, _Relation.owner.value, _Relation.editor.value}
        existing_owners_rels = await self._get_resource_owners(resource_type, resource_id_str, consistency)
        n_existing_owners = len(existing_owners_rels)
        for member in members:
            rel = Relationship(
                resource=project_res,
                relation=_Relation.from_role(member.role).value,
                subject=SubjectReference(object=_AuthzConverter.user(member.user_id)),
            )
            existing_rel_filter = RelationshipFilter(
                resource_type=resource_type.value,
                optional_resource_id=resource_id_str,
                optional_subject_filter=SubjectFilter(
                    subject_type=ResourceType.user, optional_subject_id=member.user_id
                ),
            )
            existing_rels_iter: AsyncIterable[ReadRelationshipsResponse] = self.client.ReadRelationships(
                ReadRelationshipsRequest(consistency=consistency, relationship_filter=existing_rel_filter)
            )
            existing_rels = [i async for i in existing_rels_iter if i.relationship.relation in expected_user_roles]
            if len(existing_rels) > 0:
                # The existing relationships should be deleted if all goes well and added back in if we have to undo
                existing_rel = existing_rels[0]
                if existing_rel.relationship != rel:
                    if existing_rel.relationship.relation == _Relation.owner.value:
                        n_existing_owners -= 1
                    elif rel.relation == _Relation.owner.value:
                        n_existing_owners += 1

                    add_members.extend(
                        [
                            RelationshipUpdate(
                                operation=RelationshipUpdate.OPERATION_TOUCH,
                                relationship=rel,
                            ),
                            # NOTE: The old role for the user still exists and we have to remove it
                            # if not both the old and new role for the same user will be present in the database
                            RelationshipUpdate(
                                operation=RelationshipUpdate.OPERATION_DELETE,
                                relationship=existing_rel.relationship,
                            ),
                        ]
                    )
                    undo.extend(
                        [
                            RelationshipUpdate(
                                operation=RelationshipUpdate.OPERATION_DELETE,
                                relationship=rel,
                            ),
                            RelationshipUpdate(
                                operation=RelationshipUpdate.OPERATION_TOUCH, relationship=existing_rel.relationship
                            ),
                        ]
                    )
                    output.append(MembershipChange(member, Change.UPDATE))
                for rel_to_remove in existing_rels[1:]:
                    # NOTE: This means that the user has more than 1 role on the project - which should not happen
                    # But if this does occur then we simply delete the extra roles of the user here.
                    logger.warning(
                        f"Removing additional unexpected role {rel_to_remove.relationship.relation} "
                        f"of user {member.user_id} on project {resource_id}, "
                        f"kept role {existing_rel.relationship.relation} which will be updated to {rel.relation}."
                    )
                    add_members.append(
                        RelationshipUpdate(
                            operation=RelationshipUpdate.OPERATION_DELETE,
                            relationship=rel_to_remove.relationship,
                        ),
                    )
                    undo.append(
                        RelationshipUpdate(
                            operation=RelationshipUpdate.OPERATION_TOUCH, relationship=rel_to_remove.relationship
                        ),
                    )
                    output.append(MembershipChange(member, Change.REMOVE))
            else:
                if rel.relation == _Relation.owner.value:
                    n_existing_owners += 1
                # The new relationship is added if all goes well and deleted if we have to undo
                add_members.append(
                    RelationshipUpdate(operation=RelationshipUpdate.OPERATION_TOUCH, relationship=rel),
                )
                undo.append(
                    RelationshipUpdate(operation=RelationshipUpdate.OPERATION_DELETE, relationship=rel),
                )
                output.append(MembershipChange(member, Change.ADD))

        if n_existing_owners == 0:
            raise errors.ValidationError(
                message="You are trying to change the role of all the owners of the project, which is not allowed. "
                "Assign at least one user as owner and then retry."
            )

        change = _AuthzChange(
            apply=WriteRelationshipsRequest(updates=add_members), undo=WriteRelationshipsRequest(updates=undo)
        )
        await self.client.WriteRelationships(change.apply)
        return output

    @_is_allowed(Scope.CHANGE_MEMBERSHIP)
    async def remove_project_members(
        self,
        user: base_models.APIUser,
        resource_type: ResourceType,
        resource_id: ULID,
        user_ids: list[str],
        *,
        zed_token: ZedToken | None = None,
    ) -> list[MembershipChange]:
        """Remove the specific members from the project, then return the list of members that were removed."""
        resource_id_str = str(resource_id)
        consistency = Consistency(at_least_as_fresh=zed_token) if zed_token else Consistency(fully_consistent=True)
        add_members: list[RelationshipUpdate] = []
        remove_members: list[RelationshipUpdate] = []
        output: list[MembershipChange] = []
        existing_owners_rels = await self._get_resource_owners(resource_type, resource_id_str, consistency)
        existing_owners: set[str] = {rel.relationship.subject.object.object_id for rel in existing_owners_rels}
        for user_id in user_ids:
            if user_id == "*":
                raise errors.ValidationError(message="Cannot remove a project member with ID '*'")
            existing_rel_filter = RelationshipFilter(
                resource_type=resource_type.value,
                optional_resource_id=resource_id_str,
                optional_subject_filter=SubjectFilter(subject_type=ResourceType.user, optional_subject_id=user_id),
            )
            existing_rels: AsyncIterable[ReadRelationshipsResponse] = self.client.ReadRelationships(
                ReadRelationshipsRequest(consistency=consistency, relationship_filter=existing_rel_filter)
            )
            # NOTE: We have to make sure that when we undo we only put back relationships that existed already.
            # Blindly undoing everything that was passed in may result in adding things that weren't there before.
            async for existing_rel in existing_rels:
                if existing_rel.relationship.relation == _Relation.owner.value and user_id in existing_owners:
                    if len(existing_owners) == 1:
                        raise errors.ValidationError(
                            message="You are trying to remove the single last owner of the project, "
                            "which is not allowed. Assign another user as owner and then retry."
                        )
                    existing_owners.remove(user_id)
                add_members.append(
                    RelationshipUpdate(
                        operation=RelationshipUpdate.OPERATION_TOUCH, relationship=existing_rel.relationship
                    )
                )
                remove_members.append(
                    RelationshipUpdate(
                        operation=RelationshipUpdate.OPERATION_DELETE, relationship=existing_rel.relationship
                    )
                )
                output.append(
                    MembershipChange(
                        Member(
                            Role(existing_rel.relationship.relation),
                            existing_rel.relationship.subject.object.object_id,
                            resource_id,
                        ),
                        Change.REMOVE,
                    ),
                )
        change = _AuthzChange(
            apply=WriteRelationshipsRequest(updates=remove_members), undo=WriteRelationshipsRequest(updates=add_members)
        )
        await self.client.WriteRelationships(change.apply)
        return output

    async def _get_admin_user_ids(self) -> list[str]:
        platform = _AuthzConverter.platform()
        sub_filter = SubjectFilter(subject_type=ResourceType.user.value)
        rel_filter = RelationshipFilter(
            resource_type=platform.object_type,
            optional_resource_id=platform.object_id,
            optional_subject_filter=sub_filter,
        )
        existing_admins: AsyncIterable[ReadRelationshipsResponse] = self.client.ReadRelationships(
            ReadRelationshipsRequest(
                consistency=Consistency(fully_consistent=True),
                relationship_filter=rel_filter,
            )
        )
        return [admin.relationship.subject.object.object_id async for admin in existing_admins]

    def _add_admin(self, user_id: str) -> _AuthzChange:
        """Add a deployment-wide administrator in the authorization database."""
        rel = Relationship(
            resource=_AuthzConverter.platform(),
            relation=_Relation.admin.value,
            subject=_AuthzConverter.user_subject(user_id),
        )
        apply = WriteRelationshipsRequest(
            updates=[RelationshipUpdate(operation=RelationshipUpdate.OPERATION_TOUCH, relationship=rel)]
        )
        undo = WriteRelationshipsRequest(
            updates=[RelationshipUpdate(operation=RelationshipUpdate.OPERATION_DELETE, relationship=rel)]
        )
        return _AuthzChange(apply=apply, undo=undo)

    async def _remove_admin(self, user_id: str) -> _AuthzChange:
        """Remove a deployment-wide administrator from the authorization database."""
        existing_admin_ids = await self._get_admin_user_ids()
        rel = Relationship(
            resource=_AuthzConverter.platform(),
            relation=_Relation.admin.value,
            subject=_AuthzConverter.user_subject(user_id),
        )
        apply = WriteRelationshipsRequest(
            updates=[RelationshipUpdate(operation=RelationshipUpdate.OPERATION_DELETE, relationship=rel)]
        )
        undo = WriteRelationshipsRequest()
        if user_id in existing_admin_ids:
            undo = WriteRelationshipsRequest(
                updates=[RelationshipUpdate(operation=RelationshipUpdate.OPERATION_TOUCH, relationship=rel)]
            )
        return _AuthzChange(apply=apply, undo=undo)

    def _add_group(self, group: Group) -> _AuthzChange:
        """Add a group to the authorization database."""
        if not group.id:
            raise errors.ProgrammingError(
                message="Cannot create a group in the authorization database if its ID is missing."
            )
        creator = SubjectReference(object=_AuthzConverter.user(group.created_by))
        group_res = _AuthzConverter.group(group.id)
        creator_is_owner = Relationship(resource=group_res, relation=_Relation.owner.value, subject=creator)
        all_users = SubjectReference(object=_AuthzConverter.all_users())
        all_anon_users = SubjectReference(object=_AuthzConverter.anonymous_users())
        group_in_platform = Relationship(
            resource=group_res,
            relation=_Relation.group_platform.value,
            subject=SubjectReference(object=self._platform),
        )
        all_users_are_public_viewers = Relationship(
            resource=group_res,
            relation=_Relation.public_viewer.value,
            subject=all_users,
        )
        all_anon_users_are_public_viewers = Relationship(
            resource=group_res,
            relation=_Relation.public_viewer.value,
            subject=all_anon_users,
        )
        relationships = [
            creator_is_owner,
            group_in_platform,
            all_users_are_public_viewers,
            all_anon_users_are_public_viewers,
        ]
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

    @_is_allowed(Scope.CHANGE_MEMBERSHIP)
    async def upsert_group_members(
        self,
        user: base_models.APIUser,
        resource_type: ResourceType,
        resource_id: ULID,
        members: list[Member],
        *,
        zed_token: ZedToken | None = None,
    ) -> list[MembershipChange]:
        """Insert or update group member roles."""
        consistency = Consistency(at_least_as_fresh=zed_token) if zed_token else Consistency(fully_consistent=True)
        group_res = _AuthzConverter.group(resource_id)
        add_members: list[RelationshipUpdate] = []
        undo: list[RelationshipUpdate] = []
        output: list[MembershipChange] = []
        resource_id_str = str(resource_id)
        expected_user_roles = {_Relation.viewer.value, _Relation.owner.value, _Relation.editor.value}
        existing_owners_rels = await self._get_resource_owners(resource_type, resource_id_str, consistency)
        n_existing_owners = len(existing_owners_rels)
        for member in members:
            rel = Relationship(
                resource=group_res,
                relation=_Relation.from_role(member.role).value,
                subject=SubjectReference(object=_AuthzConverter.user(member.user_id)),
            )
            existing_rel_filter = RelationshipFilter(
                resource_type=resource_type.value,
                optional_resource_id=resource_id_str,
                optional_subject_filter=SubjectFilter(
                    subject_type=ResourceType.user, optional_subject_id=member.user_id
                ),
            )
            existing_rels_result: AsyncIterable[ReadRelationshipsResponse] = self.client.ReadRelationships(
                ReadRelationshipsRequest(consistency=consistency, relationship_filter=existing_rel_filter)
            )

            existing_rels = [i async for i in existing_rels_result if i.relationship.relation in expected_user_roles]
            if len(existing_rels) > 0:
                # The existing relationships should be deleted if all goes well and added back in if we have to undo
                existing_rel = existing_rels[0]
                if existing_rel.relationship != rel:
                    if existing_rel.relationship.relation == _Relation.owner.value:
                        n_existing_owners -= 1
                    elif rel.relation == _Relation.owner.value:
                        n_existing_owners += 1

                    add_members.extend(
                        [
                            RelationshipUpdate(
                                operation=RelationshipUpdate.OPERATION_TOUCH,
                                relationship=rel,
                            ),
                            # NOTE: The old role for the user still exists and we have to remove it
                            # if not both the old and new role for the same user will be present in the database
                            RelationshipUpdate(
                                operation=RelationshipUpdate.OPERATION_DELETE,
                                relationship=existing_rel.relationship,
                            ),
                        ]
                    )
                    undo.extend(
                        [
                            RelationshipUpdate(
                                operation=RelationshipUpdate.OPERATION_TOUCH,
                                relationship=existing_rel.relationship,
                            ),
                            RelationshipUpdate(
                                operation=RelationshipUpdate.OPERATION_DELETE,
                                relationship=rel,
                            ),
                        ]
                    )
                    output.append(MembershipChange(member, Change.UPDATE))
                for rel_to_remove in existing_rels[1:]:
                    # NOTE: This means that the user has more than 1 role on the group - which should not happen
                    # But if this does occur then we simply delete the extra roles of the user here.
                    logger.warning(
                        f"Removing additional unexpected role {rel_to_remove.relationship.relation} "
                        f"of user {member.user_id} on group {resource_id}, "
                        f"kept role {existing_rel.relationship.relation} which will be updated to {rel.relation}."
                    )
                    add_members.append(
                        RelationshipUpdate(
                            operation=RelationshipUpdate.OPERATION_DELETE,
                            relationship=rel_to_remove.relationship,
                        ),
                    )
                    undo.append(
                        RelationshipUpdate(
                            operation=RelationshipUpdate.OPERATION_TOUCH, relationship=rel_to_remove.relationship
                        ),
                    )
                    output.append(MembershipChange(member, Change.REMOVE))
            else:
                if rel.relation == _Relation.owner.value:
                    n_existing_owners += 1

                # The new relationship is added if all goes well and deleted if we have to undo
                add_members.append(
                    RelationshipUpdate(operation=RelationshipUpdate.OPERATION_TOUCH, relationship=rel),
                )
                undo.append(
                    RelationshipUpdate(operation=RelationshipUpdate.OPERATION_DELETE, relationship=rel),
                )
                output.append(MembershipChange(member, Change.ADD))

        if n_existing_owners == 0:
            raise errors.ValidationError(
                message="You are trying to change the role of all the owners of the group, which is not allowed. "
                "Assign at least one user as owner and then retry."
            )

        change = _AuthzChange(
            apply=WriteRelationshipsRequest(updates=add_members), undo=WriteRelationshipsRequest(updates=undo)
        )
        await self.client.WriteRelationships(change.apply)
        return output

    @_is_allowed(Scope.CHANGE_MEMBERSHIP)
    async def remove_group_members(
        self,
        user: base_models.APIUser,
        resource_type: ResourceType,
        resource_id: ULID,
        user_ids: list[str],
        *,
        zed_token: ZedToken | None = None,
    ) -> list[MembershipChange]:
        """Remove the specific members from the group, then return the list of members that were removed."""
        consistency = Consistency(at_least_as_fresh=zed_token) if zed_token else Consistency(fully_consistent=True)
        add_members: list[RelationshipUpdate] = []
        remove_members: list[RelationshipUpdate] = []
        output: list[MembershipChange] = []
        existing_owners_rels: list[ReadRelationshipsResponse] | None = None
        resource_id_str = str(resource_id)
        for user_id in user_ids:
            if user_id == "*":
                raise errors.ValidationError(message="Cannot remove a group member with ID '*'")
            existing_rel_filter = RelationshipFilter(
                resource_type=resource_type.value,
                optional_resource_id=resource_id_str,
                optional_subject_filter=SubjectFilter(subject_type=ResourceType.user, optional_subject_id=user_id),
            )
            existing_rels: AsyncIterable[ReadRelationshipsResponse] = self.client.ReadRelationships(
                ReadRelationshipsRequest(consistency=consistency, relationship_filter=existing_rel_filter)
            )
            # NOTE: We have to make sure that when we undo we only put back relationships that existed already.
            # Blindly undoing everything that was passed in may result in adding things that weren't there before.
            async for existing_rel in existing_rels:
                if existing_rel.relationship.relation == _Relation.owner.value:
                    if existing_owners_rels is None:
                        existing_owners_rels = await self._get_resource_owners(
                            resource_type, resource_id_str, consistency
                        )
                    if len(existing_owners_rels) == 1:
                        raise errors.ValidationError(
                            message="You are trying to remove the single last owner of the group, "
                            "which is not allowed. Assign another user as owner and then retry."
                        )
                add_members.append(
                    RelationshipUpdate(
                        operation=RelationshipUpdate.OPERATION_TOUCH, relationship=existing_rel.relationship
                    )
                )
                remove_members.append(
                    RelationshipUpdate(
                        operation=RelationshipUpdate.OPERATION_DELETE, relationship=existing_rel.relationship
                    )
                )
                output.append(
                    MembershipChange(
                        Member(
                            Role(existing_rel.relationship.relation),
                            existing_rel.relationship.subject.object.object_id,
                            resource_id,
                        ),
                        Change.REMOVE,
                    ),
                )
        change = _AuthzChange(
            apply=WriteRelationshipsRequest(updates=remove_members), undo=WriteRelationshipsRequest(updates=add_members)
        )
        await self.client.WriteRelationships(change.apply)
        return output

    def _add_user_namespace(self, namespace: Namespace) -> _AuthzChange:
        """Add a user namespace to the authorization database."""
        if not namespace.id:
            raise errors.ProgrammingError(
                message="Cannot create a user namespace in the authorization database if its ID is missing."
            )
        creator = SubjectReference(object=_AuthzConverter.user(namespace.created_by))
        namespace_res = _AuthzConverter.user_namespace(namespace.id)
        creator_is_owner = Relationship(resource=namespace_res, relation=_Relation.owner.value, subject=creator)
        all_users = SubjectReference(object=_AuthzConverter.all_users())
        all_anon_users = SubjectReference(object=_AuthzConverter.anonymous_users())
        namespace_in_platform = Relationship(
            resource=namespace_res,
            relation=_Relation.user_namespace_platform.value,
            subject=SubjectReference(object=self._platform),
        )
        all_users_are_public_viewers = Relationship(
            resource=namespace_res,
            relation=_Relation.public_viewer.value,
            subject=all_users,
        )
        all_anon_users_are_public_viewers = Relationship(
            resource=namespace_res,
            relation=_Relation.public_viewer.value,
            subject=all_anon_users,
        )
        relationships = [
            creator_is_owner,
            namespace_in_platform,
            all_users_are_public_viewers,
            all_anon_users_are_public_viewers,
        ]
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

    # TODO: remove this method and replace it with _remove_entity()
    async def _remove_user_namespace(self, user_id: str, zed_token: ZedToken | None = None) -> _AuthzChange:
        """Remove the user namespace from the authorization database."""
        consistency = Consistency(at_least_as_fresh=zed_token) if zed_token else Consistency(fully_consistent=True)
        rel_filter = RelationshipFilter(resource_type=ResourceType.user_namespace.value, optional_resource_id=user_id)
        responses: AsyncIterable[ReadRelationshipsResponse] = self.client.ReadRelationships(
            ReadRelationshipsRequest(consistency=consistency, relationship_filter=rel_filter)
        )
        rels: list[Relationship] = []
        async for response in responses:
            rels.append(response.relationship)
        apply = WriteRelationshipsRequest(
            updates=[RelationshipUpdate(operation=RelationshipUpdate.OPERATION_DELETE, relationship=i) for i in rels]
        )
        undo = WriteRelationshipsRequest(
            updates=[RelationshipUpdate(operation=RelationshipUpdate.OPERATION_TOUCH, relationship=i) for i in rels]
        )
        return _AuthzChange(apply=apply, undo=undo)
