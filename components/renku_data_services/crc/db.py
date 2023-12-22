"""Adapter based on SQLAlchemy.

These adapters currently do a few things (1) generate SQL queries, (2) apply resource access controls,
(3) fetch the SQL results and (4) format them into a workable representation. In the future and as the code
grows it is worth looking into separating this functionality into separate classes rather than having
it all in one place.
"""
from asyncio import gather
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, cast

from sqlalchemy import NullPool, create_engine, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, selectinload, sessionmaker
from sqlalchemy.sql import Select, and_, not_, or_
from sqlalchemy.sql.expression import false, true

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.crc import models
from renku_data_services.crc import orm as schemas
from renku_data_services.k8s.quota import QuotaRepository


class _Base:
    def __init__(self, session_maker: Callable[..., AsyncSession], quotas_repo: QuotaRepository):
        self.session_maker = session_maker  # type: ignore[call-overload]
        self.quotas_repo = quotas_repo


def _resource_pool_access_control(
    api_user: base_models.APIUser,
    stmt: Select[Tuple[schemas.ResourcePoolORM]],
) -> Select[Tuple[schemas.ResourcePoolORM]]:
    """Modifies a select query to list resource pools based on whether the user is logged in or not."""
    output = stmt
    match (api_user.is_authenticated, api_user.is_admin):
        case True, False:
            # The user is logged in but not an admin
            api_user_has_default_pool_access = not_(
                # NOTE: The only way to check that a user is allowed to access the default pool is that such a
                # record does NOT EXIST in the database
                select(schemas.UserORM.no_default_access)
                .where(and_(schemas.UserORM.keycloak_id == api_user.id, schemas.UserORM.no_default_access == true()))
                .exists()
            )  # type: ignore[var-annotated]
            output = output.join(schemas.UserORM, schemas.ResourcePoolORM.users, isouter=True).where(
                or_(
                    schemas.UserORM.keycloak_id == api_user.id,  # the user is part of the pool
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
    stmt: Select[Tuple[schemas.ResourceClassORM]],
) -> Select[Tuple[schemas.ResourceClassORM]]:
    """Adjust the select statement for classes based on whether the user is logged in or not."""
    output = stmt
    match (api_user.is_authenticated, api_user.is_admin):
        case True, False:
            # The user is logged in but is not an admin
            api_user_has_default_pool_access = not_(
                # NOTE: The only way to check that a user is allowed to access the default pool is that such a
                # record does NOT EXIST in the database
                select(schemas.UserORM.no_default_access)
                .where(and_(schemas.UserORM.keycloak_id == api_user.id, schemas.UserORM.no_default_access == true()))
                .exists()
            )  # type: ignore[var-annotated]
            output = output.join(schemas.UserORM, schemas.ResourcePoolORM.users, isouter=True).where(
                or_(
                    schemas.UserORM.keycloak_id == api_user.id,  # the user is part of the pool
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
            output = output.join(schemas.UserORM, schemas.ResourcePoolORM.users, isouter=True).where(
                schemas.ResourcePoolORM.public == true(),
            )
    return output


def _only_admins(f):
    """Decorator that errors out if the user is not an admin.

    It expects the APIUser model to be a named parameter in the decorated function or
    to be the first parameter (after self).
    """

    @wraps(f)
    async def decorated_function(self, *args, **kwargs):
        api_user = None
        if "api_user" in kwargs:
            api_user = kwargs["api_user"]
        elif len(args) >= 1:
            api_user = args[0]
        if api_user is None or not api_user.is_admin:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")

        # the user is authenticated and is an admin
        response = await f(self, *args, **kwargs)
        return response

    return decorated_function


class ResourcePoolRepository(_Base):
    """The adapter used for accessing resource pools with SQLAlchemy."""

    def initialize(self, sync_connection_url: str, rp: models.ResourcePool):
        """Add the default resource pool if it does not already exist."""
        engine = create_engine(sync_connection_url, poolclass=NullPool)
        session_maker = sessionmaker(
            engine,
            class_=Session,
            expire_on_commit=True,
        )  # type: ignore[call-overload]
        with session_maker() as session:
            with session.begin():
                stmt = select(schemas.ResourcePoolORM.default == true())
                res = session.execute(stmt)
                default_rp = res.scalars().first()
                if default_rp is None:
                    orm = schemas.ResourcePoolORM.load(rp)
                    session.add(orm)

    async def get_resource_pools(
        self, api_user: base_models.APIUser, id: Optional[int] = None, name: Optional[str] = None
    ) -> List[models.ResourcePool]:
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
            output: List[models.ResourcePool] = []
            for rp in orms:
                quota = self.quotas_repo.get_quota(rp.quota) if rp.quota else None
                output.append(rp.dump(quota))
            return output

    async def filter_resource_pools(
        self,
        api_user: base_models.APIUser,
        cpu: float = 0,
        memory: int = 0,
        max_storage: int = 0,
        gpu: int = 0,
    ) -> List[models.ResourcePool]:
        """Get resource pools from database with indication of which resource class matches the specified crtieria."""
        async with self.session_maker() as session:
            criteria = and_(
                schemas.ResourceClassORM.cpu >= cpu,
                schemas.ResourceClassORM.gpu >= gpu,
                schemas.ResourceClassORM.memory >= memory,
                schemas.ResourceClassORM.max_storage >= max_storage,
            )
            stmt = (
                select(schemas.ResourceClassORM)
                .add_columns(criteria.label("matching"))
                .order_by(schemas.ResourceClassORM.resource_pool_id, schemas.ResourceClassORM.name)
                .join(schemas.ResourcePoolORM, schemas.ResourceClassORM.resource_pool)
                .options(selectinload(schemas.ResourceClassORM.resource_pool))
            )
            # NOTE: The line below ensures that the right users can access the right resources, do not remove.
            stmt = _classes_user_access_control(api_user, stmt)
            res = await session.execute(stmt)
            output: Dict[int, models.ResourcePool] = {}
            for res_class, matching in res.all():
                if res_class.resource_pool_id is None or res_class.resource_pool is None:
                    continue
                rc_data = res_class.dump()
                rc_data = cast(models.ResourceClass, rc_data)
                rc = rc_data.update(matching=matching)
                if res_class.resource_pool_id not in output:
                    quota = (
                        self.quotas_repo.get_quota(res_class.resource_pool.quota)
                        if res_class.resource_pool.quota
                        else None
                    )
                    output[res_class.resource_pool_id] = res_class.resource_pool.dump(quota)
                    output[res_class.resource_pool_id].classes.clear()
                output[res_class.resource_pool_id].classes.append(rc)
            return sorted(output.values(), key=lambda i: i.id if i.id else 0)

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
        async with self.session_maker() as session:
            async with session.begin():
                if orm.default:
                    stmt = select(schemas.ResourcePoolORM).where(schemas.ResourcePoolORM.default == true())
                    res = await session.execute(stmt)
                    default_rps = res.scalars().all()
                    if len(default_rps) >= 1:
                        raise errors.ValidationError(
                            message="There can only be one default resource pool and one already exists."
                        )
                session.add(orm)
        return orm.dump(quota)

    async def get_classes(
        self,
        api_user: base_models.APIUser,
        id: Optional[int] = None,
        name: Optional[str] = None,
        resource_pool_id: Optional[int] = None,
    ) -> List[models.ResourceClass]:
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
        async with self.session_maker() as session:
            async with session.begin():
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
    async def update_resource_pool(
        self, api_user: base_models.APIUser, id: int, put: bool, **kwargs
    ) -> models.ResourcePool:
        """Update an existing resource pool in the database."""
        rp: Optional[schemas.ResourcePoolORM] = None
        async with self.session_maker() as session:
            async with session.begin():
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
                # NOTE: The .update method on the model validates the update to the resource pool
                old_rp_model = rp.dump(quota)
                new_rp_model = old_rp_model.update(**kwargs)
                new_classes = None
                new_classes_coroutines = []
                for key, val in kwargs.items():
                    match key:
                        case "name" | "public" | "default":
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
                                        api_user, resource_pool_id=id, resource_class_id=class_id, put=put, **cls
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
        async with self.session_maker() as session:
            async with session.begin():
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
    async def delete_resource_class(self, api_user: base_models.APIUser, resource_pool_id: int, resource_class_id: int):
        """Delete a specific resource class."""
        async with self.session_maker() as session:
            async with session.begin():
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
        self, api_user: base_models.APIUser, resource_pool_id: int, resource_class_id: int, put: bool, **kwargs
    ) -> models.ResourceClass:
        """Update a specific resource class."""
        async with self.session_maker() as session:
            async with session.begin():
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
                            v = cast(List[Dict[str, str | bool]], v)
                            existing_affinities: Dict[str, schemas.NodeAffintyORM] = {
                                i.key: i for i in cls.node_affinities
                            }
                            new_affinities: Dict[str, schemas.NodeAffintyORM] = {
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
                            if put:
                                # REMOVE an affinity
                                for existing_affinity_key, existing_affinity in existing_affinities.items():
                                    if existing_affinity_key not in new_affinities.keys():
                                        cls.node_affinities.remove(existing_affinity)
                        case "tolerations":
                            v = cast(List[str], v)
                            existing_tolerations: Dict[str, schemas.TolerationORM] = {
                                tol.key: tol for tol in cls.tolerations
                            }
                            new_tolerations: Dict[str, schemas.TolerationORM] = {
                                tol: schemas.TolerationORM(key=tol) for tol in v
                            }
                            for new_tol_key, new_tol in new_tolerations.items():
                                if new_tol_key not in existing_tolerations.keys():
                                    # CREATE a brand new toleration
                                    cls.tolerations.append(new_tol)
                            if put:
                                # REMOVE a toleration
                                for existing_tol_key, existing_tol in existing_tolerations.items():
                                    if existing_tol_key not in new_tolerations.keys():
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
    async def get_tolerations(self, api_user: base_models.APIUser, resource_pool_id: int, class_id: int) -> List[str]:
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
    async def delete_tolerations(self, api_user: base_models.APIUser, resource_pool_id: int, class_id: int):
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
    ) -> List[models.NodeAffinity]:
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
    async def delete_affinities(self, api_user: base_models.APIUser, resource_pool_id: int, class_id: int):
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


class UserRepository(_Base):
    """The adapter used for accessing users with SQLAlchemy."""

    @_only_admins
    async def get_users(
        self,
        *,
        api_user: base_models.APIUser,
        keycloak_id: Optional[str] = None,
        resource_pool_id: Optional[int] = None,
    ) -> List[base_models.User]:
        """Get users from the database."""
        async with self.session_maker() as session:
            async with session.begin():
                if resource_pool_id is not None:
                    stmt = (
                        select(schemas.ResourcePoolORM)
                        .where(schemas.ResourcePoolORM.id == resource_pool_id)
                        .options(selectinload(schemas.ResourcePoolORM.users))
                    )
                    if keycloak_id is not None:
                        stmt = stmt.join(schemas.ResourcePoolORM.users)
                        stmt = stmt.where(schemas.UserORM.keycloak_id == keycloak_id)
                    res = await session.execute(stmt)
                    rp = res.scalars().first()
                    if rp is None:
                        raise errors.MissingResourceError(
                            message=f"Resource pool with id {resource_pool_id} does not exist"
                        )
                    return [user.dump() for user in rp.users]
                else:
                    stmt_usr = select(schemas.UserORM)
                    if keycloak_id is not None:
                        stmt_usr = stmt_usr.where(schemas.UserORM.keycloak_id == keycloak_id)
                    res_usr = await session.execute(stmt_usr)
                    orms = res_usr.scalars().all()
                    return [orm.dump() for orm in orms]

    @_only_admins
    async def insert_user(self, api_user: base_models.APIUser, user: base_models.User) -> base_models.User:
        """Insert a user in the database."""
        orm = schemas.UserORM.load(user)
        async with self.session_maker() as session:
            async with session.begin():
                session.add(orm)
        return orm.dump()

    @_only_admins
    async def delete_user(self, api_user: base_models.APIUser, id: str):
        """Remove a user from the database."""
        async with self.session_maker() as session:
            async with session.begin():
                stmt = select(schemas.UserORM).where(schemas.UserORM.keycloak_id == id)
                res = await session.execute(stmt)
                user = res.scalars().first()
                if user is None:
                    return None
                await session.delete(user)
        return None

    async def get_user_resource_pools(
        self,
        api_user: base_models.APIUser,
        keycloak_id: str,
        resource_pool_id: Optional[int] = None,
        resource_pool_name: Optional[str] = None,
    ) -> List[models.ResourcePool]:
        """Get resource pools that a specific user has access to."""
        async with self.session_maker() as session:
            async with session.begin():
                if not api_user.is_admin and api_user.id != keycloak_id:
                    raise errors.ValidationError(
                        message="Users cannot query for resource pools that belong to other users."
                    )
                stmt: Select[Any] = (
                    select(schemas.UserORM)
                    .where(schemas.UserORM.keycloak_id == keycloak_id)
                    .options(selectinload(schemas.UserORM.resource_pools))
                )
                res = await session.execute(stmt)
                user: Optional[schemas.UserORM] = res.scalars().first()
                if user is None:
                    raise errors.MissingResourceError(message=f"The user with keycloak id {keycloak_id} does not exist")

                stmt = select(schemas.ResourcePoolORM).options(selectinload(schemas.ResourcePoolORM.classes))
                stmt = stmt.where(
                    or_(
                        schemas.ResourcePoolORM.public == true(),
                        schemas.ResourcePoolORM.users.any(schemas.UserORM.keycloak_id == keycloak_id),
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
                output: List[models.ResourcePool] = []
                for rp in rps:
                    quota = self.quotas_repo.get_quota(rp.quota) if rp.quota else None
                    output.append(rp.dump(quota))
                return output

    @_only_admins
    async def update_user_resource_pools(
        self, api_user: base_models.APIUser, keycloak_id: str, resource_pool_ids: List[int], append: bool = True
    ) -> List[models.ResourcePool]:
        """Update the resource pools that a specific user has access to."""
        async with self.session_maker() as session:
            async with session.begin():
                stmt = (
                    select(schemas.UserORM)
                    .where(schemas.UserORM.keycloak_id == keycloak_id)
                    .options(selectinload(schemas.UserORM.resource_pools))
                )
                res = await session.execute(stmt)
                user: Optional[schemas.UserORM] = res.scalars().first()
                if user is None:
                    raise errors.MissingResourceError(message=f"The user with keycloak id {keycloak_id} does not exist")
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
                        raise errors.NoDefaultPoolAccessError(
                            message=f"User with keycloak id {keycloak_id} cannot access the default resource pool"
                        )
                if append:
                    user.resource_pools.extend(rps_to_add)
                else:
                    user.resource_pools = list(rps_to_add)
                output: List[models.ResourcePool] = []
                for rp in rps_to_add:
                    quota = self.quotas_repo.get_quota(rp.quota) if rp.quota else None
                    output.append(rp.dump(quota))
                return output

    @_only_admins
    async def delete_resource_pool_user(self, api_user: base_models.APIUser, resource_pool_id: int, keycloak_id: str):
        """Remove a user from a specific resource pool."""
        async with self.session_maker() as session:
            async with session.begin():
                sub = (
                    select(schemas.UserORM.id)
                    .join(schemas.ResourcePoolORM, schemas.UserORM.resource_pools)
                    .where(schemas.UserORM.keycloak_id == keycloak_id)
                    .where(schemas.ResourcePoolORM.id == resource_pool_id)
                )
                stmt = delete(schemas.resource_pools_users).where(schemas.resource_pools_users.c.user_id.in_(sub))
                await session.execute(stmt)

    @_only_admins
    async def update_resource_pool_users(
        self, api_user: base_models.APIUser, resource_pool_id: int, users: List[base_models.User], append: bool = True
    ) -> List[base_models.User]:
        """Update the users that have access to a specific resource pool."""
        async with self.session_maker() as session:
            async with session.begin():
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
                    no_default_rp_access_users = [u for u in users if u.no_default_access]
                    if no_default_rp_access_users:
                        no_default_rp_access_users_str = ", ".join([str(u.id) for u in no_default_rp_access_users])
                        raise errors.NoDefaultPoolAccessError(
                            message=f"Users cannot access default resource pool: [{no_default_rp_access_users_str}]"
                        )
                user_ids_to_add_req = [user.keycloak_id for user in users]
                stmt_usr = select(schemas.UserORM).where(schemas.UserORM.keycloak_id.in_(user_ids_to_add_req))
                res_usr = await session.execute(stmt_usr)
                users_to_add_exist = res_usr.scalars().all()
                user_ids_to_add_exist = [i.keycloak_id for i in users_to_add_exist]
                users_to_add_missing = [
                    schemas.UserORM(keycloak_id=i.keycloak_id, no_default_access=i.no_default_access)
                    for i in users
                    if i.keycloak_id not in user_ids_to_add_exist
                ]
                if append:
                    rp.users.extend(list(users_to_add_exist) + users_to_add_missing)
                else:
                    rp.users = list(users_to_add_exist) + users_to_add_missing
                return [usr.dump() for usr in rp.users]

    @_only_admins
    async def update_user(self, api_user: base_models.APIUser, keycloak_id: str, **kwargs) -> base_models.User:
        """Update a specific user."""
        async with self.session_maker() as session:
            async with session.begin():
                stmt = select(schemas.UserORM).where(schemas.UserORM.keycloak_id == keycloak_id)
                res = await session.execute(stmt)
                user: Optional[schemas.UserORM] = res.scalars().first()
                if not user:
                    raise errors.MissingResourceError(
                        message=f"The user with keycloak ID {keycloak_id} does not exist."
                    )
                for field_name, field_value in kwargs.items():
                    setattr(user, field_name, field_value)
                return user.dump()
