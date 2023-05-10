"""Adapter based on SQLAlchemy.

These adapters currently do a few things (1) generate SQL queries, (2) apply resource access controls,
(3) fetch the SQL results and (4) format them into a workable representation. In the future and as the code
grows it is worth looking into separating this functionality into separate classes rather than having
it all in one place.
"""
from functools import wraps
from typing import List, Optional, Tuple

from alembic import command, config
from sqlalchemy import create_engine, delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import selectinload, sessionmaker
from sqlalchemy.sql import Select

import models
from db import schemas
from models import errors


class _Base:
    def __init__(self, sync_sqlalchemy_url: str, async_sqlalchemy_url: str, debug: bool = False):
        self.engine = create_async_engine(async_sqlalchemy_url, echo=debug)
        self.sync_engine = create_engine(sync_sqlalchemy_url, echo=debug)
        self.session_maker = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )  # type: ignore[call-overload]

    def do_migrations(self):
        """Migrate the database to the required revision.

        From: https://alembic.sqlalchemy.org/en/latest/cookbook.html#programmatic-api-use-connection-sharing-with-asyncio  # noqa: E501
        """
        with self.sync_engine.begin() as conn:
            cfg = config.Config("alembic.ini")
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")


def _resource_pool_access_control(
    api_user: models.APIUser,
    stmt: Select[Tuple[schemas.ResourcePoolORM]],
    keycloak_id: Optional[str] = None,
) -> Select[Tuple[schemas.ResourcePoolORM]]:
    """Modifies a select query to list resource pools based on whether the user is logged in or not."""
    output = stmt
    match (api_user.is_authenticated, api_user.is_admin):
        case True, False:
            # The user is logged in but not an admin, they can see resource pools they have been granted access to
            # or resource pools that are marked as default.
            if keycloak_id is not None and api_user.id != keycloak_id:
                raise errors.ValidationError(
                    message="Your user ID should match the user ID for which you are querying resource pools."
                )
            output = output.join_from(schemas.UserORM, schemas.UserORM.resource_pools).where(
                or_(schemas.UserORM.keycloak_id == api_user.id, schemas.ResourcePoolORM.default == True)  # noqa: E712
            )
        case True, True:
            # The user is logged in and is an admin, they can see all resource pools
            if keycloak_id is not None:
                output = output.join_from(schemas.UserORM, schemas.UserORM.resource_pools).where(
                    schemas.UserORM.keycloak_id == keycloak_id
                )
        case _:
            # The user is not logged in, they can see only the default resource pools
            output = output.where(schemas.ResourcePoolORM.default == True)  # noqa: E712
    return output


def _classes_user_access_control(
    api_user: models.APIUser,
    stmt: Select[Tuple[schemas.ResourceClassORM]],
) -> Select[Tuple[schemas.ResourceClassORM]]:
    """Adjust the select statement for classes based on whether the user is logged in or not."""
    output = stmt
    if api_user.is_authenticated and not api_user.is_admin:
        # The user is logged in but is not an admin (they have access to resource pools
        # they have access to and to default resource pools)
        output = output.join(schemas.UserORM, schemas.ResourcePoolORM.users).where(
            schemas.UserORM.keycloak_id == api_user.id
        )
    return output


def _quota_user_access_control(
    api_user: models.APIUser, stmt: Select[Tuple[schemas.QuotaORM]]
) -> Select[Tuple[schemas.QuotaORM]]:
    """Adjust the select statement for a quota based on whether the user is logged in or not."""
    output = stmt
    if api_user.is_authenticated and not api_user.is_admin:
        # The user is logged in but is not an admin, they can see only a quota from a resource pool they have
        # been granted access to or from default resource pools.
        output = output.join(schemas.UserORM, schemas.ResourcePoolORM.users).where(
            or_(
                schemas.UserORM.keycloak_id == api_user.id,
                schemas.ResourcePoolORM.default == True,  # noqa: E712
            )
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

    async def get_resource_pools(
        self, api_user: models.APIUser, id: Optional[int] = None, name: Optional[str] = None
    ) -> List[models.ResourcePool]:
        """Get resource pools from database."""
        async with self.session_maker() as session:
            stmt = select(schemas.ResourcePoolORM).options(
                selectinload(schemas.ResourcePoolORM.quota), selectinload(schemas.ResourcePoolORM.classes)
            )
            if name is not None:
                stmt = stmt.where(schemas.ResourcePoolORM.name == name)
            if id is not None:
                stmt = stmt.where(schemas.ResourcePoolORM.id == id)
            # NOTE: The line below ensures that the right users can access the right resources, do not remove.
            stmt = _resource_pool_access_control(api_user, stmt)
            res = await session.execute(stmt)
            orms = res.scalars().all()
            return [orm.dump() for orm in orms]

    @_only_admins
    async def insert_resource_pool(
        self, api_user: models.APIUser, resource_pool: models.ResourcePool
    ) -> models.ResourcePool:
        """Insert resource pool into database."""
        if not api_user.is_admin:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")
        orm = schemas.ResourcePoolORM.load(resource_pool)
        async with self.session_maker() as session:
            async with session.begin():
                session.add(orm)
        return orm.dump()

    async def get_quota(self, api_user: models.APIUser, resource_pool_id: int) -> Optional[models.Quota]:
        """Get a quota for a specific resource pool."""

        async with self.session_maker() as session:
            stmt = select(schemas.QuotaORM).join(schemas.ResourcePoolORM, schemas.QuotaORM.resource_pool)
            # NOTE: The line below ensures that the right users can access the right resources, do not remove.
            stmt = _quota_user_access_control(api_user, stmt)
            if resource_pool_id is not None:
                stmt = stmt.where(schemas.ResourcePoolORM.id == resource_pool_id)
            res = await session.execute(stmt)
            orm: Optional[schemas.QuotaORM] = res.scalars().first()
            if not orm:
                return None
            return orm.dump()

    async def get_classes(
        self,
        api_user: models.APIUser,
        id: Optional[int] = None,
        name: Optional[str] = None,
        resource_pool_id: Optional[int] = None,
    ) -> List[models.ResourceClass]:
        """Get classes from the database."""
        async with self.session_maker() as session:
            stmt = select(schemas.ResourceClassORM).join(
                schemas.ResourcePoolORM, schemas.ResourceClassORM.resource_pool
            )
            if resource_pool_id is not None:
                stmt = stmt.where(schemas.ResourcePoolORM.id == resource_pool_id)
            if id is not None:
                stmt = stmt.where(schemas.ResourceClassORM.id == id)
            if name is not None:
                stmt = stmt.where(schemas.ResourceClassORM.name == name)
            # NOTE: The line below ensures that the right users can access the right resources, do not remove.
            stmt = _classes_user_access_control(api_user, stmt)
            stmt = stmt
            res = await session.execute(stmt)
            orms = res.scalars().all()
            return [orm.dump() for orm in orms]

    @_only_admins
    async def insert_resource_class(
        self, api_user: models.APIUser, resource_class: models.ResourceClass, *, resource_pool_id: Optional[int] = None
    ) -> models.ResourceClass:
        """Insert a resource class in the database."""
        if not api_user.is_admin:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")
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
                    cls.resource_pool = rp
                    cls.resource_pool_id = rp.id
                session.add(cls)
        return cls.dump()

    @_only_admins
    async def update_quota(self, api_user: models.APIUser, resource_pool_id: int, **kwargs) -> models.Quota:
        """Update an existing quota in the database."""
        if not api_user.is_admin:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")
        if len(kwargs) == 0:
            quota = await self.get_quota(api_user=api_user, resource_pool_id=resource_pool_id)
            if quota is None:
                raise errors.MissingResourceError(message=f"Resource pool with id {resource_pool_id} cannot be found")
            return quota
        async with self.session_maker() as session:
            async with session.begin():
                stmt = (
                    update(schemas.QuotaORM)
                    .where(schemas.QuotaORM.resource_pool_id == resource_pool_id)
                    .values(**kwargs)
                    .returning(schemas.QuotaORM)
                )
                res = await session.execute(stmt)
                orm = res.scalars().first()
        if orm is None:
            raise errors.MissingResourceError(message=f"Resource pool with id {resource_pool_id} cannot be found")
        return orm.dump()

    @_only_admins
    async def update_resource_pool(self, api_user: models.APIUser, id: int, **kwargs) -> models.ResourcePool:
        """Update an existing resource pool in the database."""
        if not api_user.is_admin:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")
        rp: Optional[schemas.ResourcePoolORM] = None
        async with self.session_maker() as session:
            async with session.begin():
                stmt = (
                    select(schemas.ResourcePoolORM)
                    .where(schemas.ResourcePoolORM.id == id)
                    .options(selectinload(schemas.ResourcePoolORM.classes), selectinload(schemas.ResourcePoolORM.quota))
                )
                res = await session.execute(stmt)
                rp = res.scalars().first()
                if rp is None:
                    raise errors.MissingResourceError(message=f"Resource pool with id {id} cannot be found")
                if len(kwargs) == 0:
                    return rp.dump()
                for key, val in kwargs.items():
                    match key:
                        case "name":
                            setattr(rp, key, val)
                        case "quota":
                            for qkey, qval in kwargs["quota"].items():
                                setattr(rp.quota, qkey, qval)
                        case "classes":
                            for cls in val:
                                class_id = cls.pop("id")
                                if len(cls) == 0:
                                    raise errors.ValidationError(
                                        message="More fields than the id of the class "
                                        "should be provided when updating it"
                                    )
                                stmt_cls = (
                                    update(schemas.ResourceClassORM)
                                    .where(schemas.ResourceClassORM.id == class_id)
                                    .where(schemas.ResourceClassORM.resource_pool_id == id)
                                    .values(**cls)
                                    .returning(schemas.ResourceClassORM)
                                )
                                res = await session.execute(stmt_cls)
                                updated_cls = res.scalars().first()
                                if updated_cls is None:
                                    raise errors.MissingResourceError(
                                        message=f"Class with id {class_id} does not exist in the resource pool"
                                    )
                        case _:
                            pass

                return rp.dump()

    @_only_admins
    async def delete_resource_pool(self, api_user: models.APIUser, id: int):
        """Delete a resource pool from the database."""
        if not api_user.is_admin:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")
        async with self.session_maker() as session:
            async with session.begin():
                stmt = select(schemas.ResourcePoolORM).where(schemas.ResourcePoolORM.id == id)
                res = await session.execute(stmt)
                rp = res.scalars().first()
                if rp is not None:
                    await session.delete(rp)

    @_only_admins
    async def delete_resource_class(self, api_user: models.APIUser, resource_pool_id: int, resource_class_id: int):
        """Delete a specific resource class."""
        if not api_user.is_admin:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")
        async with self.session_maker() as session:
            async with session.begin():
                stmt = (
                    select(schemas.ResourceClassORM)
                    .where(schemas.ResourceClassORM.id == resource_class_id)
                    .where(schemas.ResourceClassORM.resource_pool_id == resource_pool_id)
                )
                res = await session.execute(stmt)
                cls = res.scalars().first()
                if cls is None:
                    return None
                await session.delete(cls)

    @_only_admins
    async def update_resource_class(
        self, api_user: models.APIUser, resource_pool_id: int, resource_class_id: int, **kwargs
    ) -> models.ResourceClass:
        """Update a specific resource class."""
        if not api_user.is_admin:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")
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
                for k, v in kwargs.items():
                    setattr(cls, k, v)
                return cls.dump()


class UserRepository(_Base):
    """The adapter used for accessing users with SQLAlchemy."""

    @_only_admins
    async def get_users(
        self,
        *,
        api_user: models.APIUser,
        keycloak_id: Optional[str] = None,
        resource_pool_id: Optional[int] = None,
    ) -> List[models.User]:
        """Get users from the database."""
        if not api_user.is_admin and api_user.id != keycloak_id:
            raise errors.Unauthorized(message="Users can only request information about themselves.")
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
    async def insert_user(self, api_user: models.APIUser, user: models.User) -> models.User:
        """Inser a user in the database."""
        if not api_user.is_admin:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")
        orm = schemas.UserORM.load(user)
        async with self.session_maker() as session:
            async with session.begin():
                session.add(orm)
        return orm.dump()

    @_only_admins
    async def delete_user(self, api_user: models.APIUser, id: str):
        """Remove a user from the database."""
        if not api_user.is_admin:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")
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
        api_user: models.APIUser,
        keycloak_id: str,
        resource_pool_id: Optional[int] = None,
        resource_pool_name: Optional[str] = None,
    ) -> List[models.ResourcePool]:
        """Get resource pools that a specific user has access to."""
        async with self.session_maker() as session:
            async with session.begin():
                stmt = select(schemas.ResourcePoolORM).options(
                    selectinload(schemas.ResourcePoolORM.quota), selectinload(schemas.ResourcePoolORM.classes)
                )
                if resource_pool_name is not None:
                    stmt = stmt.where(schemas.ResourcePoolORM.name == resource_pool_name)
                if resource_pool_id is not None:
                    stmt = stmt.where(schemas.ResourcePoolORM.id == resource_pool_id)
                # NOTE: The line below ensures that the right users can access the right resources, do not remove.
                stmt = _resource_pool_access_control(api_user, stmt, keycloak_id=keycloak_id)
                res = await session.execute(stmt)
                rps: List[schemas.ResourcePoolORM] = res.scalars().all()
                return [rp.dump() for rp in rps]

    @_only_admins
    async def update_user_resource_pools(
        self, api_user: models.APIUser, keycloak_id: str, resource_pool_ids: List[int], append: bool = True
    ) -> List[models.ResourcePool]:
        """Update the resource pools that a specific user has access to."""
        if not api_user.is_admin:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")
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
                    .options(selectinload(schemas.ResourcePoolORM.quota), selectinload(schemas.ResourcePoolORM.classes))
                )
                res = await session.execute(stmt_rp)
                rps_to_add = res.scalars().all()
                if len(rps_to_add) != len(resource_pool_ids):
                    missing_rps = set(resource_pool_ids).difference(set([i.id for i in rps_to_add]))
                    raise errors.MissingResourceError(
                        message=f"The resource pools with ids: {missing_rps} do not exist."
                    )
                if append:
                    user.resource_pools.extend(rps_to_add)
                else:
                    user.resource_pools = rps_to_add
                return [rp.dump() for rp in rps_to_add]

    @_only_admins
    async def delete_resource_pool_user(self, api_user: models.APIUser, resource_pool_id: int, keycloak_id: str):
        """Remove a user from a specific resource pool."""
        if not api_user.is_admin:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")
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
        self, api_user: models.APIUser, resource_pool_id: int, users: List[models.User], append: bool = True
    ) -> List[models.User]:
        """Update the users that have access to a specific resource pool."""
        if not api_user.is_admin:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")
        async with self.session_maker() as session:
            async with session.begin():
                stmt = (
                    select(schemas.ResourcePoolORM)
                    .where(schemas.ResourcePoolORM.id == resource_pool_id)
                    .options(
                        selectinload(schemas.ResourcePoolORM.users),
                        selectinload(schemas.ResourcePoolORM.classes),
                        selectinload(schemas.ResourcePoolORM.quota),
                    )
                )
                res = await session.execute(stmt)
                rp: Optional[schemas.ResourcePoolORM] = res.scalars().first()
                if rp is None:
                    raise errors.MissingResourceError(
                        message=f"The resource pool with id {resource_pool_id} does not exist"
                    )
                user_ids_to_add_req = [user.keycloak_id for user in users]
                stmt_usr = select(schemas.UserORM).where(schemas.UserORM.keycloak_id.in_(user_ids_to_add_req))
                res = await session.execute(stmt_usr)
                users_to_add_exist = res.scalars().all()
                user_ids_to_add_exist = [i.keycloak_id for i in users_to_add_exist]
                users_to_add_missing = [
                    schemas.UserORM(keycloak_id=i.keycloak_id)
                    for i in users
                    if i.keycloak_id not in user_ids_to_add_exist
                ]
                if append:
                    rp.users.extend(users_to_add_exist + users_to_add_missing)
                else:
                    rp.users = users_to_add_exist + users_to_add_missing
                return [usr.dump() for usr in rp.users]
