"""Adapter based on SQLAlchemy.

These adapters currently do a few things (1) generate SQL queries, (2) apply resource access controls,
(3) fetch the SQL results and (4) format them into a workable representation. In the future and as the code
grows it is worth looking into separating this functionality into separate classes rather than having
it all in one place.
"""
from asyncio import gather
from functools import wraps
from typing import Any, Dict, List, Optional, Tuple, cast

from sqlalchemy import create_engine, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session, selectinload, sessionmaker
from sqlalchemy.sql import Select, and_
from sqlalchemy.sql.expression import false, true

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.crc import models
from renku_data_services.crc import orm as schemas


class _Base:
    def __init__(self, sync_sqlalchemy_url: str, async_sqlalchemy_url: str, debug: bool = False):
        self.engine = create_async_engine(async_sqlalchemy_url, echo=debug)
        self.sync_engine = create_engine(sync_sqlalchemy_url, echo=debug)
        self.session_maker = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )  # type: ignore[call-overload]


def _resource_pool_access_control(
    api_user: base_models.APIUser,
    stmt: Select[Tuple[schemas.ResourcePoolORM]],
    keycloak_id: Optional[str] = None,
) -> Select[Tuple[schemas.ResourcePoolORM]]:
    """Modifies a select query to list resource pools based on whether the user is logged in or not."""
    output = stmt
    match (api_user.is_authenticated, api_user.is_admin):
        case True, False:
            # The user is logged in but not an admin, they can see resource pools they have been granted access to
            # or resource pools that are marked as public.
            if keycloak_id is not None and api_user.id != keycloak_id:
                raise errors.ValidationError(
                    message="Your user ID should match the user ID for which you are querying resource pools."
                )
            output = output.join(schemas.UserORM, schemas.ResourcePoolORM.users, isouter=True).where(
                # TODO: Should .public be .default
                or_(schemas.UserORM.keycloak_id == api_user.id, schemas.ResourcePoolORM.public == true())
            )
        case True, True:
            # The user is logged in and is an admin, they can see all resource pools
            if keycloak_id is not None:
                output = output.join(schemas.UserORM, schemas.ResourcePoolORM.users, isouter=True).where(
                    schemas.UserORM.keycloak_id == keycloak_id
                )
        case _:
            # The user is not logged in, they can see only the public resource pools
            output = output.where(schemas.ResourcePoolORM.public == true())
    return output


def _classes_user_access_control(
    api_user: base_models.APIUser,
    stmt: Select[Tuple[schemas.ResourceClassORM]],
) -> Select[Tuple[schemas.ResourceClassORM]]:
    """Adjust the select statement for classes based on whether the user is logged in or not."""
    output = stmt
    if api_user.is_authenticated and not api_user.is_admin:
        # The user is logged in but is not an admin (they have access to resource pools
        # they have access to and to default resource pools)
        output = output.join(schemas.UserORM, schemas.ResourcePoolORM.users, isouter=True).where(
            or_(
                schemas.UserORM.keycloak_id == api_user.id,
                schemas.ResourcePoolORM.public == true(),
            )
        )
    elif not api_user.is_authenticated:
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

    def initialize(self, rp: models.ResourcePool):
        """Add the default resource pool if it does not already exist."""
        session_maker = sessionmaker(
            self.sync_engine,
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
            return [orm.dump() for orm in orms]

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
            orms = cast(List[Tuple[schemas.ResourceClassORM, bool]], res.all())
            rcs: Dict[int, List[models.ResourceClass]] = {}
            rps: Dict[int, schemas.ResourcePoolORM] = {}
            output: List[models.ResourcePool] = []
            for res_class, matching in orms:
                if res_class.resource_pool_id is None or res_class.resource_pool is None:
                    continue
                rc_data = res_class.dump()
                rc_matching = models.ResourceClass(
                    name=rc_data.name,
                    cpu=rc_data.cpu,
                    memory=rc_data.memory,
                    max_storage=rc_data.max_storage,
                    gpu=rc_data.gpu,
                    id=rc_data.id,
                    default=res_class.default,
                    default_storage=res_class.default_storage,
                    matching=matching,
                )
                if res_class.resource_pool_id not in rcs:
                    rcs[res_class.resource_pool_id] = [rc_matching]
                else:
                    rcs[res_class.resource_pool_id].append(rc_matching)
                if res_class.resource_pool_id not in rps:
                    rps[res_class.resource_pool_id] = res_class.resource_pool
            for rp_id, rp in sorted(rps.items(), key=lambda x: x[0]):
                output.append(
                    models.ResourcePool(
                        name=rp.name,
                        classes=rcs[rp_id],
                        quota=rp.quota,
                        id=rp.id,
                        default=rp.default,
                        public=rp.public,
                    )
                )
            return output

    @_only_admins
    async def insert_resource_pool(
        self, api_user: base_models.APIUser, resource_pool: models.ResourcePool
    ) -> models.ResourcePool:
        """Insert resource pool into database."""
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
        return orm.dump()

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
                    rp: schemas.ResourcePoolORM = res.scalars().first()
                    if rp is None:
                        raise errors.MissingResourceError(
                            message=f"Resource pool with id {resource_pool_id} does not exist."
                        )
                    if cls.default and len(rp.classes) > 0 and any([icls.default for icls in rp.classes]):
                        raise errors.ValidationError(
                            message="There can only be one default resource class per resource pool."
                        )
                    cls.resource_pool = rp
                    cls.resource_pool_id = rp.id

                session.add(cls)
        return cls.dump()

    @_only_admins
    async def update_resource_pool(self, api_user: base_models.APIUser, id: int, **kwargs) -> models.ResourcePool:
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
                if len(kwargs) == 0:
                    return rp.dump()
                # NOTE: The .update method on the model validates the update to the resource pool
                rp.dump().update(**kwargs)
                new_classes = None
                new_classes_coroutines = []
                for key, val in kwargs.items():
                    match key:
                        case "name" | "public" | "default" | "quota":
                            setattr(rp, key, val)
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
                output = rp.dump()
                if new_classes is not None and len(new_classes) > 0:
                    output = output.update(classes=new_classes)
                return output

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
                    return rp.dump()
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
        self, api_user: base_models.APIUser, resource_pool_id: int, resource_class_id: int, **kwargs
    ) -> models.ResourceClass:
        """Update a specific resource class."""
        async with self.session_maker() as session:
            async with session.begin():
                stmt = (
                    select(schemas.ResourceClassORM)
                    .where(schemas.ResourceClassORM.id == resource_class_id)
                    .where(schemas.ResourceClassORM.resource_pool_id == resource_pool_id)
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
                if not cls.default:
                    raise errors.ValidationError(message="Only the default resource class can be updated.")
                for k, v in kwargs.items():
                    match k:
                        case "node_affinities":
                            for affinity in v:
                                matched_affinity = next(
                                    filter(lambda x: x.key == affinity["key"], cls.node_affinities), None
                                )
                                if matched_affinity:
                                    # NOTE: The node affinity is already present in the resource class, update it
                                    matched_affinity.required_during_scheduling = affinity.required_during_scheduling
                                else:
                                    # NOTE: The node affinity does not exist, create it
                                    cls.node_affinities.append(affinity)
                        case _:
                            setattr(cls, k, v)
                return cls.dump()


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
                    stmt = select(schemas.UserORM)
                    if keycloak_id is not None:
                        stmt = stmt.where(schemas.UserORM.keycloak_id == keycloak_id)
                    res = await session.execute(stmt)
                    orms = res.scalars().all()
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
                if resource_pool_name is not None:
                    stmt = stmt.where(schemas.ResourcePoolORM.name == resource_pool_name)
                if resource_pool_id is not None:
                    stmt = stmt.where(schemas.ResourcePoolORM.id == resource_pool_id)
                if user.no_default_access:
                    stmt = stmt.where(schemas.ResourcePoolORM.default == false())
                # NOTE: The line below ensures that the right users can access the right resources, do not remove.
                stmt = _resource_pool_access_control(api_user, stmt, keycloak_id=keycloak_id)
                res = await session.execute(stmt)
                rps: List[schemas.ResourcePoolORM] = res.scalars().all()
                if user.no_default_access:
                    rps = [rp for rp in rps if not rp.default]
                return [rp.dump() for rp in rps]

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
                res = await session.execute(stmt_rp)
                rps_to_add = res.scalars().all()
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
                    user.resource_pools = rps_to_add
                return [rp.dump() for rp in rps_to_add]

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
                res = await session.execute(stmt_usr)
                users_to_add_exist = res.scalars().all()
                user_ids_to_add_exist = [i.keycloak_id for i in users_to_add_exist]
                users_to_add_missing = [
                    schemas.UserORM(keycloak_id=i.keycloak_id, no_default_access=i.no_default_access)
                    for i in users
                    if i.keycloak_id not in user_ids_to_add_exist
                ]
                if append:
                    rp.users.extend(users_to_add_exist + users_to_add_missing)
                else:
                    rp.users = users_to_add_exist + users_to_add_missing
                return [usr.dump() for usr in rp.users]
