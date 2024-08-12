"""Adapter based on SQLAlchemy.

These adapters currently do a few things (1) generate SQL queries, (2) apply resource access controls,
(3) fetch the SQL results and (4) format them into a workable representation. In the future and as the code
grows it is worth looking into separating this functionality into separate classes rather than having
it all in one place.
"""

from asyncio import gather
from collections.abc import Callable, Collection, Coroutine, Sequence
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Concatenate, Optional, ParamSpec, TypeVar, cast

from sqlalchemy import NullPool, create_engine, delete, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, selectinload, sessionmaker
from sqlalchemy.sql import Select, and_, not_, or_
from sqlalchemy.sql.expression import false, true

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.crc import models
from renku_data_services.crc import orm as schemas
from renku_data_services.k8s.quota import QuotaRepository
from renku_data_services.users.db import UserRepo


class _Base:
    def __init__(self, session_maker: Callable[..., AsyncSession], quotas_repo: QuotaRepository) -> None:
        self.session_maker = session_maker
        self.quotas_repo = quotas_repo


def _resource_pool_access_control(
    api_user: base_models.APIUser,
    stmt: Select[tuple[schemas.ResourcePoolORM]],
) -> Select[tuple[schemas.ResourcePoolORM]]:
    """Modifies a select query to list resource pools based on whether the user is logged in or not."""
    output = stmt
    match (api_user.is_authenticated, api_user.is_admin):
        case True, False:
            # The user is logged in but not an admin
            api_user_has_default_pool_access = not_(
                # NOTE: The only way to check that a user is allowed to access the default pool is that such a
                # record does NOT EXIST in the database
                select(schemas.RPUserORM.no_default_access)
                .where(
                    and_(schemas.RPUserORM.keycloak_id == api_user.id, schemas.RPUserORM.no_default_access == true())
                )
                .exists()
            )
            output = output.join(schemas.RPUserORM, schemas.ResourcePoolORM.users, isouter=True).where(
                or_(
                    schemas.RPUserORM.keycloak_id == api_user.id,  # the user is part of the pool
                    and_(  # the pool is not default but is public
                        schemas.ResourcePoolORM.default != true(), schemas.ResourcePoolORM.public == true()
                    ),
                    and_(  # the pool is default and the user is not prohibited from accessing it
                        schemas.ResourcePoolORM.default == true(),
                        api_user_has_default_pool_access,
                    ),
                )
            )
        case True, True:
            # The user is logged in and is an admin, they can see all resource pools
            pass
        case False, _:
            # The user is not logged in, they can see only the public resource pools
            output = output.where(schemas.ResourcePoolORM.public == true())
    return output


def _classes_user_access_control(
    api_user: base_models.APIUser,
    stmt: Select[tuple[schemas.ResourceClassORM]],
) -> Select[tuple[schemas.ResourceClassORM]]:
    """Adjust the select statement for classes based on whether the user is logged in or not."""
    output = stmt
    match (api_user.is_authenticated, api_user.is_admin):
        case True, False:
            # The user is logged in but is not an admin
            api_user_has_default_pool_access = not_(
                # NOTE: The only way to check that a user is allowed to access the default pool is that such a
                # record does NOT EXIST in the database
                select(schemas.RPUserORM.no_default_access)
                .where(
                    and_(schemas.RPUserORM.keycloak_id == api_user.id, schemas.RPUserORM.no_default_access == true())
                )
                .exists()
            )
            output = output.join(schemas.RPUserORM, schemas.ResourcePoolORM.users, isouter=True).where(
                or_(
                    schemas.RPUserORM.keycloak_id == api_user.id,  # the user is part of the pool
                    and_(  # the pool is not default but is public
                        schemas.ResourcePoolORM.default != true(), schemas.ResourcePoolORM.public == true()
                    ),
                    and_(  # the pool is default and the user is not prohibited from accessing it
                        schemas.ResourcePoolORM.default == true(),
                        api_user_has_default_pool_access,
                    ),
                )
            )
        case True, True:
            # The user is logged in and is an admin, they can see all resource classes
            pass
        case False, _:
            # The user is not logged in, they can see only the classes from public resource pools
            output = output.join(schemas.RPUserORM, schemas.ResourcePoolORM.users, isouter=True).where(
                schemas.ResourcePoolORM.public == true(),
            )
    return output


_P = ParamSpec("_P")
_T = TypeVar("_T")


def _only_admins(
    f: Callable[Concatenate[Any, _P], Coroutine[Any, Any, _T]],
) -> Callable[Concatenate[Any, _P], Coroutine[Any, Any, _T]]:
    """Decorator that errors out if the user is not an admin.

    It expects the APIUser model to be a named parameter in the decorated function or
    to be the first parameter (after self).
    """

    @wraps(f)
    async def decorated_function(self: Any, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        api_user = None
        if "api_user" in kwargs:
            api_user = kwargs["api_user"]
        elif len(args) >= 1:
            api_user = args[0]
        if api_user is not None and not isinstance(api_user, base_models.APIUser):
            raise errors.ProgrammingError(message="Expected user parameter is not of type APIUser.")
        if api_user is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")
        if not api_user.is_admin:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

        # the user is authenticated and is an admin
        response = await f(self, *args, **kwargs)
        return response

    return decorated_function


class ResourcePoolRepository(_Base):
    """The adapter used for accessing resource pools with SQLAlchemy."""

    def initialize(self, sync_connection_url: str, rp: models.ResourcePool) -> None:
        """Add the default resource pool if it does not already exist."""
        engine = create_engine(sync_connection_url, poolclass=NullPool)
        session_maker = sessionmaker(
            engine,
            class_=Session,
            expire_on_commit=True,
        )
        with session_maker() as session, session.begin():
            stmt = select(schemas.ResourcePoolORM.default == true())
            res = session.execute(stmt)
            default_rp = res.scalars().first()
            if default_rp is None:
                orm = schemas.ResourcePoolORM.load(rp)
                session.add(orm)

    async def get_resource_pools(
        self, api_user: base_models.APIUser, id: Optional[int] = None, name: Optional[str] = None
    ) -> list[models.ResourcePool]:
        """Get resource pools from database."""
        async with self.session_maker() as session:
            stmt = select(schemas.ResourcePoolORM).options(selectinload(schemas.ResourcePoolORM.classes))
            if name is not None:
                stmt = stmt.where(schemas.ResourcePoolORM.name == name)
            if id is not None:
                stmt = stmt.where(schemas.ResourcePoolORM.id == id)
            # NOTE: The line below ensures that the right users can access the right resources, do not remove.
            stmt = _resource_pool_access_control(api_user, stmt)
            res = await session.execute(stmt)
            orms = res.scalars().all()
            output: list[models.ResourcePool] = []
            for rp in orms:
                quota = self.quotas_repo.get_quota(rp.quota) if rp.quota else None
                output.append(rp.dump(quota))
            return output

    async def get_default_resource_class(self) -> models.ResourceClass:
        """Get the default reosurce class in the default resource pool."""
        async with self.session_maker() as session:
            stmt = (
                select(schemas.ResourceClassORM)
                .where(schemas.ResourceClassORM.default == true())
                .where(schemas.ResourceClassORM.resource_pool.has(schemas.ResourcePoolORM.default == true()))
            )
            res = await session.scalar(stmt)
            if res is None:
                raise errors.ProgrammingError(
                    message="Could not find the default class from the default resource pool, but this has to exist."
                )
            return res.dump()

    async def filter_resource_pools(
        self,
        api_user: base_models.APIUser,
        cpu: float = 0,
        memory: int = 0,
        max_storage: int = 0,
        gpu: int = 0,
    ) -> list[models.ResourcePool]:
        """Get resource pools from database with indication of which resource class matches the specified crtieria."""
        async with self.session_maker() as session:
            criteria = models.ResourceClass(
                name="criteria",
                cpu=cpu,
                gpu=gpu,
                memory=memory,
                max_storage=max_storage,
                # NOTE: the default storage has to be <= max_storage but is not used for filtering classes,
                # only the max_storage is used to filter resource classes that match a request
                default_storage=max_storage,
            )
            stmt = (
                select(schemas.ResourcePoolORM)
                .join(schemas.ResourcePoolORM.classes)
                .order_by(
                    schemas.ResourcePoolORM.id,
                    schemas.ResourcePoolORM.name,
                    schemas.ResourceClassORM.id,
                    schemas.ResourceClassORM.name,
                )
            )
            # NOTE: The line below ensures that the right users can access the right resources, do not remove.
            stmt = _resource_pool_access_control(api_user, stmt)
            res = await session.execute(stmt)
            return [i.dump(self.quotas_repo.get_quota(i.quota), criteria) for i in res.unique().scalars().all()]

    @_only_admins
    async def insert_resource_pool(
        self, api_user: base_models.APIUser, resource_pool: models.ResourcePool
    ) -> models.ResourcePool:
        """Insert resource pool into database."""
        quota = None
        if resource_pool.quota:
            for rc in resource_pool.classes:
                if not resource_pool.quota.is_resource_class_compatible(rc):
                    raise errors.ValidationError(
                        message=f"The quota {quota} is not compatible with resource class {rc}"
                    )
            quota = self.quotas_repo.create_quota(resource_pool.quota)
            resource_pool = resource_pool.set_quota(quota)
        orm = schemas.ResourcePoolORM.load(resource_pool)
        async with self.session_maker() as session, session.begin():
            if orm.idle_threshold == 0:
                orm.idle_threshold = None
            if orm.hibernation_threshold == 0:
                orm.hibernation_threshold = None
            if orm.default:
                stmt = select(schemas.ResourcePoolORM).where(schemas.ResourcePoolORM.default == true())
                res = await session.execute(stmt)
                default_rps = res.unique().scalars().all()
                if len(default_rps) >= 1:
                    raise errors.ValidationError(
                        message="There can only be one default resource pool and one already exists."
                    )
            session.add(orm)
        return orm.dump(quota)

    async def get_classes(
        self,
        api_user: Optional[base_models.APIUser] = None,
        id: Optional[int] = None,
        name: Optional[str] = None,
        resource_pool_id: Optional[int] = None,
    ) -> list[models.ResourceClass]:
        """Get classes from the database."""
        async with self.session_maker() as session:
            stmt = select(schemas.ResourceClassORM).join(
                schemas.ResourcePoolORM, schemas.ResourceClassORM.resource_pool, isouter=True
            )
            if resource_pool_id is not None:
                stmt = stmt.where(schemas.ResourcePoolORM.id == resource_pool_id)
            if id is not None:
                stmt = stmt.where(schemas.ResourceClassORM.id == id)
            if name is not None:
                stmt = stmt.where(schemas.ResourceClassORM.name == name)

            # Apply user access control if api_user is provided
            if api_user is not None:
                # NOTE: The line below ensures that the right users can access the right resources, do not remove.
                stmt = _classes_user_access_control(api_user, stmt)

            res = await session.execute(stmt)
            orms = res.scalars().all()
            return [orm.dump() for orm in orms]

    @_only_admins
    async def insert_resource_class(
        self,
        api_user: base_models.APIUser,
        resource_class: models.ResourceClass,
        *,
        resource_pool_id: Optional[int] = None,
    ) -> models.ResourceClass:
        """Insert a resource class in the database."""
        cls = schemas.ResourceClassORM.load(resource_class)
        async with self.session_maker() as session, session.begin():
            if resource_pool_id is not None:
                stmt = select(schemas.ResourcePoolORM).where(schemas.ResourcePoolORM.id == resource_pool_id)
                res = await session.execute(stmt)
                rp = res.scalars().first()
                if rp is None:
                    raise errors.MissingResourceError(
                        message=f"Resource pool with id {resource_pool_id} does not exist."
                    )
                if cls.default and len(rp.classes) > 0 and any([icls.default for icls in rp.classes]):
                    raise errors.ValidationError(
                        message="There can only be one default resource class per resource pool."
                    )
                quota = self.quotas_repo.get_quota(rp.quota) if rp.quota else None
                if quota and not quota.is_resource_class_compatible(resource_class):
                    raise errors.ValidationError(
                        message="The resource class {resource_class} is not compatible with the quota {quota}."
                    )
                cls.resource_pool = rp
                cls.resource_pool_id = rp.id

            session.add(cls)
        return cls.dump()

    @_only_admins
    async def update_resource_pool(self, api_user: base_models.APIUser, id: int, **kwargs: Any) -> models.ResourcePool:
        """Update an existing resource pool in the database."""
        rp: Optional[schemas.ResourcePoolORM] = None
        async with self.session_maker() as session, session.begin():
            stmt = (
                select(schemas.ResourcePoolORM)
                .where(schemas.ResourcePoolORM.id == id)
                .options(selectinload(schemas.ResourcePoolORM.classes))
            )
            res = await session.execute(stmt)
            rp = res.scalars().first()
            if rp is None:
                raise errors.MissingResourceError(message=f"Resource pool with id {id} cannot be found")
            quota = self.quotas_repo.get_quota(rp.quota) if rp.quota else None
            if len(kwargs) == 0:
                return rp.dump(quota)

            if kwargs.get("idle_threshold", None) == 0:
                kwargs["idle_threshold"] = None
            if kwargs.get("hibernation_threshold", None) == 0:
                kwargs["hibernation_threshold"] = None
            # NOTE: The .update method on the model validates the update to the resource pool
            old_rp_model = rp.dump(quota)
            new_rp_model = old_rp_model.update(**kwargs)
            new_classes = None
            new_classes_coroutines = []
            for key, val in kwargs.items():
                match key:
                    case "name" | "public" | "default" | "idle_threshold" | "hibernation_threshold":
                        setattr(rp, key, val)
                    case "quota":
                        if val is None:
                            continue

                        # For updating a quota, there are two options:
                        # 1. no quota exists --> create a new one
                        # 2. a quota exists and can only be updated, not replaced (the ids, if provided, must match)

                        new_id = val.get("id")

                        if quota and quota.id is not None and new_id is not None and quota.id != new_id:
                            raise errors.ValidationError(
                                message="The ID of an existing quota cannot be updated, "
                                f"please remove the ID field from the request or use ID {quota.id}."
                            )

                        # the id must match for update
                        if quota:
                            val["id"] = quota.id or new_id

                        new_quota = models.Quota.from_dict(val)

                        if new_id or quota:
                            new_quota = self.quotas_repo.update_quota(new_quota)
                        else:
                            new_quota = self.quotas_repo.create_quota(new_quota)
                        rp.quota = new_quota.id
                        new_rp_model = new_rp_model.update(quota=new_quota)
                    case "classes":
                        new_classes = []
                        for cls in val:
                            class_id = cls.pop("id")
                            cls.pop("matching", None)
                            if len(cls) == 0:
                                raise errors.ValidationError(
                                    message="More fields than the id of the class "
                                    "should be provided when updating it"
                                )
                            new_classes_coroutines.append(
                                self.update_resource_class(
                                    api_user, resource_pool_id=id, resource_class_id=class_id, **cls
                                )
                            )
                    case _:
                        pass
            new_classes = await gather(*new_classes_coroutines)
            if new_classes is not None and len(new_classes) > 0:
                new_rp_model = new_rp_model.update(classes=new_classes)
            return new_rp_model

    @_only_admins
    async def delete_resource_pool(self, api_user: base_models.APIUser, id: int) -> Optional[models.ResourcePool]:
        """Delete a resource pool from the database."""
        async with self.session_maker() as session, session.begin():
            stmt = select(schemas.ResourcePoolORM).where(schemas.ResourcePoolORM.id == id)
            res = await session.execute(stmt)
            rp = res.scalars().first()
            if rp is not None:
                if rp.default:
                    raise errors.ValidationError(message="The default resource pool cannot be deleted.")
                await session.delete(rp)
                quota = None
                if rp.quota:
                    quota = self.quotas_repo.get_quota(rp.quota)
                    self.quotas_repo.delete_quota(rp.quota)
                return rp.dump(quota)
            return None

    @_only_admins
    async def delete_resource_class(
        self, api_user: base_models.APIUser, resource_pool_id: int, resource_class_id: int
    ) -> None:
        """Delete a specific resource class."""
        async with self.session_maker() as session, session.begin():
            stmt = (
                select(schemas.ResourceClassORM)
                .where(schemas.ResourceClassORM.id == resource_class_id)
                .where(schemas.ResourceClassORM.resource_pool_id == resource_pool_id)
            )
            res = await session.execute(stmt)
            cls = res.scalars().first()
            if cls is not None:
                if cls.default:
                    raise errors.ValidationError(message="The default resource class cannot be deleted.")
                await session.delete(cls)

    @_only_admins
    async def update_resource_class(
        self, api_user: base_models.APIUser, resource_pool_id: int, resource_class_id: int, **kwargs: Any
    ) -> models.ResourceClass:
        """Update a specific resource class."""
        async with self.session_maker() as session, session.begin():
            stmt = (
                select(schemas.ResourceClassORM)
                .where(schemas.ResourceClassORM.id == resource_class_id)
                .where(schemas.ResourceClassORM.resource_pool_id == resource_pool_id)
                .join(schemas.ResourcePoolORM, schemas.ResourceClassORM.resource_pool)
                .options(selectinload(schemas.ResourceClassORM.resource_pool))
            )
            res = await session.execute(stmt)
            cls: Optional[schemas.ResourceClassORM] = res.scalars().first()
            if cls is None:
                raise errors.MissingResourceError(
                    message=(
                        f"The resource class with id {resource_class_id} does not exist, the resource pool with "
                        f"id {resource_pool_id} does not exist or the requested resource class is not "
                        "associated with the resource pool"
                    )
                )
            for k, v in kwargs.items():
                match k:
                    case "node_affinities":
                        v = cast(list[dict[str, str | bool]], v)
                        existing_affinities: dict[str, schemas.NodeAffintyORM] = {i.key: i for i in cls.node_affinities}
                        new_affinities: dict[str, schemas.NodeAffintyORM] = {
                            i["key"]: schemas.NodeAffintyORM(**i) for i in v
                        }
                        for new_affinity_key, new_affinity in new_affinities.items():
                            if new_affinity_key in existing_affinities:
                                # UPDATE existing affinity
                                existing_affinity = existing_affinities[new_affinity_key]
                                if (
                                    new_affinity.required_during_scheduling
                                    != existing_affinity.required_during_scheduling
                                ):
                                    existing_affinity.required_during_scheduling = (
                                        new_affinity.required_during_scheduling
                                    )
                            else:
                                # CREATE a brand new affinity
                                cls.node_affinities.append(new_affinity)
                        # REMOVE an affinity
                        for existing_affinity_key, existing_affinity in existing_affinities.items():
                            if existing_affinity_key not in new_affinities:
                                cls.node_affinities.remove(existing_affinity)
                    case "tolerations":
                        v = cast(list[str], v)
                        existing_tolerations: dict[str, schemas.TolerationORM] = {
                            tol.key: tol for tol in cls.tolerations
                        }
                        new_tolerations: dict[str, schemas.TolerationORM] = {
                            tol: schemas.TolerationORM(key=tol) for tol in v
                        }
                        for new_tol_key, new_tol in new_tolerations.items():
                            if new_tol_key not in existing_tolerations:
                                # CREATE a brand new toleration
                                cls.tolerations.append(new_tol)
                        # REMOVE a toleration
                        for existing_tol_key, existing_tol in existing_tolerations.items():
                            if existing_tol_key not in new_tolerations:
                                cls.tolerations.remove(existing_tol)
                    case _:
                        setattr(cls, k, v)
            if cls.resource_pool is None:
                raise errors.BaseError(
                    message="Unexpected internal error.",
                    detail=f"The resource class {resource_class_id} is not associated with any resource pool.",
                )
            quota = self.quotas_repo.get_quota(cls.resource_pool.quota) if cls.resource_pool.quota else None
            cls_model = cls.dump()
            if quota and not quota.is_resource_class_compatible(cls_model):
                raise errors.ValidationError(
                    message=f"The resource class {cls_model} is not compatible with the quota {quota}"
                )
            return cls_model

    @_only_admins
    async def get_tolerations(self, api_user: base_models.APIUser, resource_pool_id: int, class_id: int) -> list[str]:
        """Get all tolerations of a resource class."""
        async with self.session_maker() as session:
            res_classes = await self.get_classes(api_user, class_id, resource_pool_id=resource_pool_id)
            if len(res_classes) == 0:
                raise errors.MissingResourceError(
                    message=f"The resource pool with ID {resource_pool_id} or the resource "
                    f"class with ID {class_id} do not exist, or they are not related."
                )
            stmt = select(schemas.TolerationORM).where(schemas.TolerationORM.resource_class_id == class_id)
            res = await session.execute(stmt)
            return [i.key for i in res.scalars().all()]

    @_only_admins
    async def delete_tolerations(self, api_user: base_models.APIUser, resource_pool_id: int, class_id: int) -> None:
        """Delete all tolerations for a specific resource class."""
        async with self.session_maker() as session, session.begin():
            res_classes = await self.get_classes(api_user, class_id, resource_pool_id=resource_pool_id)
            if len(res_classes) == 0:
                raise errors.MissingResourceError(
                    message=f"The resource pool with ID {resource_pool_id} or the resource "
                    f"class with ID {class_id} do not exist, or they are not related."
                )
            stmt = delete(schemas.TolerationORM).where(schemas.TolerationORM.resource_class_id == class_id)
            await session.execute(stmt)

    @_only_admins
    async def get_affinities(
        self, api_user: base_models.APIUser, resource_pool_id: int, class_id: int
    ) -> list[models.NodeAffinity]:
        """Get all affinities for a resource class."""
        async with self.session_maker() as session:
            res_classes = await self.get_classes(api_user, class_id, resource_pool_id=resource_pool_id)
            if len(res_classes) == 0:
                raise errors.MissingResourceError(
                    message=f"The resource pool with ID {resource_pool_id} or the resource "
                    f"class with ID {class_id} do not exist, or they are not related."
                )
            stmt = select(schemas.NodeAffintyORM).where(schemas.NodeAffintyORM.resource_class_id == class_id)
            res = await session.execute(stmt)
            return [i.dump() for i in res.scalars().all()]

    @_only_admins
    async def delete_affinities(self, api_user: base_models.APIUser, resource_pool_id: int, class_id: int) -> None:
        """Delete all affinities from a resource class."""
        async with self.session_maker() as session, session.begin():
            res_classes = await self.get_classes(api_user, class_id, resource_pool_id=resource_pool_id)
            if len(res_classes) == 0:
                raise errors.MissingResourceError(
                    message=f"The resource pool with ID {resource_pool_id} or the resource "
                    f"class with ID {class_id} do not exist, or they are not related."
                )
            stmt = delete(schemas.NodeAffintyORM).where(schemas.NodeAffintyORM.resource_class_id == class_id)
            await session.execute(stmt)


@dataclass
class RespositoryUsers:
    """Information about which users can access a specific resource pool."""

    resource_pool_id: int
    allowed: list[base_models.User] = field(default_factory=list)
    disallowed: list[base_models.User] = field(default_factory=list)


class UserRepository(_Base):
    """The adapter used for accessing resource pool users with SQLAlchemy."""

    def __init__(
        self, session_maker: Callable[..., AsyncSession], quotas_repo: QuotaRepository, user_repo: UserRepo
    ) -> None:
        super().__init__(session_maker, quotas_repo)
        self.kc_user_repo = user_repo

    @_only_admins
    async def get_resource_pool_users(
        self,
        *,
        api_user: base_models.APIUser,
        resource_pool_id: int,
        keycloak_id: Optional[str] = None,
    ) -> RespositoryUsers:
        """Get users of a specific resource pool from the database."""
        async with self.session_maker() as session, session.begin():
            stmt = (
                select(schemas.ResourcePoolORM)
                .where(schemas.ResourcePoolORM.id == resource_pool_id)
                .options(selectinload(schemas.ResourcePoolORM.users))
            )
            if keycloak_id is not None:
                stmt = stmt.join(schemas.ResourcePoolORM.users, isouter=True).where(
                    or_(
                        schemas.RPUserORM.keycloak_id == keycloak_id,
                        schemas.ResourcePoolORM.public == true(),
                        schemas.ResourceClassORM.default == true(),
                    )
                )
            res = await session.execute(stmt)
            rp = res.scalars().first()
            if rp is None:
                raise errors.MissingResourceError(message=f"Resource pool with id {resource_pool_id} does not exist")
            specific_user: base_models.User | None = None
            if keycloak_id:
                specific_user_res = (
                    await session.execute(select(schemas.RPUserORM).where(schemas.RPUserORM.keycloak_id == keycloak_id))
                ).scalar_one_or_none()
                specific_user = None if not specific_user_res else specific_user_res.dump()
            allowed: list[base_models.User] = []
            disallowed: list[base_models.User] = []
            if rp.default:
                disallowed_stmt = select(schemas.RPUserORM).where(schemas.RPUserORM.no_default_access == true())
                if keycloak_id:
                    disallowed_stmt = disallowed_stmt.where(schemas.RPUserORM.keycloak_id == keycloak_id)
                disallowed_res = await session.execute(disallowed_stmt)
                disallowed = [user.dump() for user in disallowed_res.scalars().all()]
                if specific_user and specific_user not in disallowed:
                    allowed = [specific_user]
            elif rp.public and not rp.default:
                if specific_user:
                    allowed = [specific_user]
            elif not rp.public and not rp.default:
                allowed = [user.dump() for user in rp.users]
            return RespositoryUsers(rp.id, allowed, disallowed)

    async def get_user_resource_pools(
        self,
        api_user: base_models.APIUser,
        keycloak_id: str,
        resource_pool_id: Optional[int] = None,
        resource_pool_name: Optional[str] = None,
    ) -> list[models.ResourcePool]:
        """Get resource pools that a specific user has access to."""
        async with self.session_maker() as session, session.begin():
            if not api_user.is_admin and api_user.id != keycloak_id:
                raise errors.ValidationError(
                    message="Users cannot query for resource pools that belong to other users."
                )

            stmt = select(schemas.ResourcePoolORM).options(selectinload(schemas.ResourcePoolORM.classes))
            stmt = stmt.where(
                or_(
                    schemas.ResourcePoolORM.public == true(),
                    schemas.ResourcePoolORM.users.any(schemas.RPUserORM.keycloak_id == keycloak_id),
                )
            )
            if resource_pool_name is not None:
                stmt = stmt.where(schemas.ResourcePoolORM.name == resource_pool_name)
            if resource_pool_id is not None:
                stmt = stmt.where(schemas.ResourcePoolORM.id == resource_pool_id)
            # NOTE: The line below ensures that the right users can access the right resources, do not remove.
            stmt = _resource_pool_access_control(api_user, stmt)
            res = await session.execute(stmt)
            rps: Sequence[schemas.ResourcePoolORM] = res.scalars().all()
            output: list[models.ResourcePool] = []
            for rp in rps:
                quota = self.quotas_repo.get_quota(rp.quota) if rp.quota else None
                output.append(rp.dump(quota))
            return output

    @_only_admins
    async def update_user_resource_pools(
        self, api_user: base_models.APIUser, keycloak_id: str, resource_pool_ids: list[int], append: bool = True
    ) -> list[models.ResourcePool]:
        """Update the resource pools that a specific user has access to."""
        async with self.session_maker() as session, session.begin():
            kc_user = await self.kc_user_repo.get_user(keycloak_id)
            if kc_user is None:
                raise errors.MissingResourceError(message=f"The user with ID {keycloak_id} does not exist")
            stmt = (
                select(schemas.RPUserORM)
                .where(schemas.RPUserORM.keycloak_id == keycloak_id)
                .options(selectinload(schemas.RPUserORM.resource_pools))
            )
            res = await session.execute(stmt)
            user = res.scalars().first()
            if user is None:
                user = schemas.RPUserORM(keycloak_id=keycloak_id)
                session.add(user)
            stmt_rp = (
                select(schemas.ResourcePoolORM)
                .where(schemas.ResourcePoolORM.id.in_(resource_pool_ids))
                .options(selectinload(schemas.ResourcePoolORM.classes))
            )
            if user.no_default_access:
                stmt_rp = stmt_rp.where(schemas.ResourcePoolORM.default == false())
            res_rp = await session.execute(stmt_rp)
            rps_to_add = res_rp.scalars().all()
            if len(rps_to_add) != len(resource_pool_ids):
                missing_rps = set(resource_pool_ids).difference(set([i.id for i in rps_to_add]))
                raise errors.MissingResourceError(
                    message=(
                        f"The resource pools with ids: {missing_rps} do not exist or user doesn't have access to "
                        "default resource pool."
                    )
                )
            if user.no_default_access:
                default_rp = next((rp for rp in rps_to_add if rp.default), None)
                if default_rp:
                    raise errors.ForbiddenError(
                        message=f"User with keycloak id {keycloak_id} cannot access the default resource pool"
                    )
            if append:
                user_rp_ids = {rp.id for rp in user.resource_pools}
                rps_to_add = [rp for rp in rps_to_add if rp.id not in user_rp_ids]
                user.resource_pools.extend(rps_to_add)
            else:
                user.resource_pools = list(rps_to_add)
            output: list[models.ResourcePool] = []
            for rp in rps_to_add:
                quota = self.quotas_repo.get_quota(rp.quota) if rp.quota else None
                output.append(rp.dump(quota))
            return output

    @_only_admins
    async def delete_resource_pool_user(
        self, api_user: base_models.APIUser, resource_pool_id: int, keycloak_id: str
    ) -> None:
        """Remove a user from a specific resource pool."""
        async with self.session_maker() as session, session.begin():
            sub = (
                select(schemas.RPUserORM.id)
                .join(schemas.ResourcePoolORM, schemas.RPUserORM.resource_pools)
                .where(schemas.RPUserORM.keycloak_id == keycloak_id)
                .where(schemas.ResourcePoolORM.id == resource_pool_id)
            )
            stmt = delete(schemas.resource_pools_users).where(schemas.resource_pools_users.c.user_id.in_(sub))
            await session.execute(stmt)

    @_only_admins
    async def update_resource_pool_users(
        self, api_user: base_models.APIUser, resource_pool_id: int, user_ids: Collection[str], append: bool = True
    ) -> list[base_models.User]:
        """Update the users to have access to a specific resource pool."""
        async with self.session_maker() as session, session.begin():
            stmt = (
                select(schemas.ResourcePoolORM)
                .where(schemas.ResourcePoolORM.id == resource_pool_id)
                .options(
                    selectinload(schemas.ResourcePoolORM.users),
                    selectinload(schemas.ResourcePoolORM.classes),
                )
            )
            res = await session.execute(stmt)
            rp: Optional[schemas.ResourcePoolORM] = res.scalars().first()
            if rp is None:
                raise errors.MissingResourceError(
                    message=f"The resource pool with id {resource_pool_id} does not exist"
                )
            if rp.default:
                # NOTE: If the resource pool is default just check if any users are prevented from having
                # default resource pool access - and remove the restriction.
                all_existing_users = await self.get_resource_pool_users(
                    api_user=api_user, resource_pool_id=resource_pool_id
                )
                users_to_modify = [user for user in all_existing_users.disallowed if user.keycloak_id in user_ids]
                return await gather(
                    *[
                        self.update_user(
                            api_user=api_user, keycloak_id=no_default_user.keycloak_id, no_default_access=False
                        )
                        for no_default_user in users_to_modify
                    ]
                )
            stmt_usr = select(schemas.RPUserORM).where(schemas.RPUserORM.keycloak_id.in_(user_ids))
            res_usr = await session.execute(stmt_usr)
            users_to_add_exist = res_usr.scalars().all()
            user_ids_to_add_exist = [i.keycloak_id for i in users_to_add_exist]
            users_to_add_missing = [
                schemas.RPUserORM(keycloak_id=user_id) for user_id in user_ids if user_id not in user_ids_to_add_exist
            ]
            if append:
                rp_user_ids = {rp.id for rp in rp.users}
                users_to_add = [u for u in list(users_to_add_exist) + users_to_add_missing if u.id not in rp_user_ids]
                rp.users.extend(users_to_add)
            else:
                rp.users = list(users_to_add_exist) + users_to_add_missing
            return [usr.dump() for usr in rp.users]

    @_only_admins
    async def update_user(self, api_user: base_models.APIUser, keycloak_id: str, **kwargs: Any) -> base_models.User:
        """Update a specific user."""
        async with self.session_maker() as session, session.begin():
            stmt = select(schemas.RPUserORM).where(schemas.RPUserORM.keycloak_id == keycloak_id)
            res = await session.execute(stmt)
            user: Optional[schemas.RPUserORM] = res.scalars().first()
            if not user:
                user = schemas.RPUserORM(keycloak_id=keycloak_id)
                session.add(user)
            allowed_updates = set(["no_default_access"])
            if not set(kwargs.keys()).issubset(allowed_updates):
                raise errors.ValidationError(
                    message=f"Only the following fields {allowed_updates} " "can be updated for a resource pool user.."
                )
            if (no_default_access := kwargs.get("no_default_access", None)) is not None:
                user.no_default_access = no_default_access
            return user.dump()
