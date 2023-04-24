"""Adapter based on SQLAlchemy."""
from typing import List, Optional

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import selectinload, sessionmaker

from src import models
from src.db import schemas
from src.models import errors


class DB:
    """The adapter used for database access with SQLAlchemy."""

    def __init__(self, sql_alchemy_url: str):
        self.engine = create_async_engine(sql_alchemy_url, echo=True)
        self.session_maker = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )  # type: ignore[call-overload]

    async def get_resource_pools(
        self, id: Optional[int] = None, name: Optional[str] = None
    ) -> List[models.ResourcePool]:
        """Get resource pools from database."""
        async with self.session_maker() as session:
            stmt = select(schemas.ResourcePoolORM).options(
                selectinload(schemas.ResourcePoolORM.classes), selectinload(schemas.ResourcePoolORM.quota)
            )
            if id is not None:
                stmt = stmt.where(schemas.ResourcePoolORM.id == id)  # type: ignore[arg-type]
            if name is not None:
                stmt = stmt.where(schemas.ResourcePoolORM.name == name)  # type: ignore[arg-type]
            res = await session.execute(stmt)
            orms = res.scalars().all()
            return [orm.dump() for orm in orms]

    async def insert_resource_pool(self, resource_pool: models.ResourcePool) -> models.ResourcePool:
        """Insert resource pool into database."""
        orm = schemas.ResourcePoolORM.load(resource_pool)
        async with self.session_maker() as session:
            async with session.begin():
                session.add(orm)
        return orm.dump()

    async def get_quota(self, resource_pool_id: int) -> Optional[models.Quota]:
        """Get a quota for a specific resource pool."""
        async with self.session_maker() as session:
            res = await session.execute(
                select(schemas.QuotaORM).where(
                    schemas.QuotaORM.resource_pool_id == resource_pool_id  # type: ignore[arg-type]
                )
            )
            orm: schemas.QuotaORM = res.scalars().first()
            if not orm:
                return None
            return orm.dump()

    async def get_classes(
        self, id: Optional[int] = None, name: Optional[str] = None, resource_pool_id: Optional[int] = None
    ) -> List[models.ResourceClass]:
        """Get classes from the database."""
        async with self.session_maker() as session:
            stmt = select(schemas.ResourceClassORM)
            if id is not None:
                stmt = stmt.where(schemas.ResourceClassORM.id == id)  # type: ignore[arg-type]
            if resource_pool_id is not None:
                stmt = stmt.where(schemas.ResourceClassORM.resource_pool_id == resource_pool_id)
            if name is not None:
                stmt = stmt.where(schemas.ResourceClassORM.name == name)
            res = await session.execute(stmt)
            orms = res.scalars().all()
            return [orm.dump() for orm in orms]

    async def get_users(
        self,
        *,
        keycloak_id: Optional[str] = None,
        username: Optional[str] = None,
        resource_pool_id: Optional[int] = None,
    ) -> List[models.User]:
        """Get users from the database."""
        async with self.session_maker() as session:
            async with session.begin():
                if resource_pool_id is not None:
                    stmt = (
                        select(schemas.ResourcePoolORM)
                        .where(schemas.ResourcePoolORM.id == resource_pool_id)  # type: ignore[arg-type]
                        .options(selectinload(schemas.ResourcePoolORM.users))
                    )
                    if username is not None or keycloak_id is not None:
                        stmt.join(schemas.ResourcePoolORM.users)
                    if keycloak_id is not None:
                        stmt = stmt.where(schemas.UserORM.keycloak_id == keycloak_id)
                    if username is not None:
                        stmt = stmt.where(schemas.UserORM.username == username)
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
                    if username is not None:
                        stmt = stmt.where(schemas.UserORM.username == username)
                    res = await session.execute(stmt)
                    orms = res.scalars().all()
                    return [orm.dump() for orm in orms]

    async def insert_user(self, user: models.User) -> models.User:
        """Inser a user in the database."""
        orm = schemas.UserORM.load(user)
        async with self.session_maker() as session:
            async with session.begin():
                session.add(orm)
        return orm.dump()

    async def delete_user(self, id: str):
        """Remove a user from the database."""
        async with self.session_maker() as session:
            async with session.begin():
                stmt = delete(schemas.UserORM).where(schemas.UserORM.keycloak_id == id)
                await session.execute(stmt)
        return None

    async def insert_resource_class(
        self, resource_class: models.ResourceClass, *, resource_pool_id: Optional[int] = None
    ) -> models.ResourceClass:
        """Insert a resource class in the database."""
        orm = schemas.ResourceClassORM.load(resource_class)
        if resource_pool_id is not None:
            orm.resource_pool_id = resource_pool_id
        async with self.session_maker() as session:
            async with session.begin():
                session.add(orm)
        return orm.dump()

    async def update_quota(self, resource_pool_id: int, **kwargs) -> models.Quota:
        """Update an existing quota in the database."""
        if len(kwargs) == 0:
            quota = await self.get_quota(resource_pool_id=resource_pool_id)
            if quota is None:
                raise errors.MissingResourceError(message=f"Resource pool with id {resource_pool_id} cannot be found")
            return quota
        async with self.session_maker() as session:
            async with session.begin():
                stmt = (
                    update(schemas.QuotaORM)
                    .where(schemas.QuotaORM.resource_pool_id == resource_pool_id)  # type: ignore[arg-type]
                    .values(**kwargs)
                    .returning(schemas.QuotaORM)
                )
                res = await session.execute(stmt)
                orm = res.scalars().first()
        if orm is None:
            raise errors.MissingResourceError(message=f"Resource pool with id {resource_pool_id} cannot be found")
        return orm.dump()

    async def update_resource_pool(self, id: int, **kwargs) -> models.ResourcePool:
        """Update an existing resource pool in the database."""
        rp: Optional[schemas.ResourcePoolORM] = None
        async with self.session_maker() as session:
            async with session.begin():
                stmt = (
                    select(schemas.ResourcePoolORM)
                    .where(schemas.ResourcePoolORM.id == id)  # type: ignore[arg-type]
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

    async def delete_resource_pool(self, id: int):
        """Delete a resource pool from the database."""
        async with self.session_maker() as session:
            async with session.begin():
                stmt = delete(schemas.ResourcePoolORM).where(schemas.ResourcePoolORM.id == id)  # type: ignore[arg-type]
                await session.execute(stmt)
        return None

    async def get_user_resource_pools(
        self, keycloak_id: str, resource_pool_name: Optional[str] = None
    ) -> List[models.ResourcePool]:
        """Get resource pools that a specific user has access to."""
        async with self.session_maker() as session:
            async with session.begin():
                stmt = (
                    select(schemas.ResourcePoolORM)
                    .join_from(schemas.UserORM, schemas.UserORM.resource_pools)
                    .where(schemas.UserORM.keycloak_id == keycloak_id)
                    .options(selectinload(schemas.ResourcePoolORM.quota), selectinload(schemas.ResourcePoolORM.classes))
                )
                if resource_pool_name is not None:
                    stmt = stmt.where(schemas.ResourcePoolORM.name == resource_pool_name)
                res = await session.execute(stmt)
                rps: List[schemas.ResourcePoolORM] = res.scalars().all()
                return [rp.dump() for rp in rps]

    async def update_user_resource_pools(
        self, keycloak_id: str, resource_pool_ids: List[int], append: bool = True
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
                    .where(schemas.ResourcePoolORM.id.in_(resource_pool_ids))  # type: ignore[union-attr]
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

    async def update_resource_pool_users(
        self, resource_pool_id: int, users: List[models.User], append: bool = True
    ) -> models.ResourcePool:
        """Update the users that have access to a specific resource pool."""
        async with self.session_maker() as session:
            async with session.begin():
                stmt = (
                    select(schemas.ResourcePoolORM)
                    .where(schemas.ResourcePoolORM.id == resource_pool_id)  # type: ignore[arg-type]
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
                    schemas.UserORM(keycloak_id=i.keycloak_id, username=i.username)
                    for i in users
                    if i.keycloak_id not in user_ids_to_add_exist
                ]
                if append:
                    rp.users.extend(users_to_add_exist + users_to_add_missing)
                else:
                    rp.users = users_to_add_exist + users_to_add_missing
                return rp.dump()

    async def delete_resource_class(self, resource_pool_id: int, resource_class_id: int):
        """Delete a specific resource class."""
        async with self.session_maker() as session:
            async with session.begin():
                stmt = (
                    delete(schemas.ResourceClassORM)
                    .where(schemas.ResourceClassORM.id == resource_class_id)  # type: ignore[arg-type]
                    .where(schemas.ResourceClassORM.resource_pool_id == resource_pool_id)
                )
                await session.execute(stmt)

    async def delete_resource_pool_user(self, resource_pool_id: int, keycloak_id: str):
        """Remove a user from a specific resource pool."""
        async with self.session_maker() as session:
            async with session.begin():
                sub = (
                    select(schemas.UserORM.id)  # type: ignore[call-overload]
                    .join(schemas.ResourcePoolORM, schemas.UserORM.resource_pools)
                    .where(schemas.UserORM.keycloak_id == keycloak_id)
                    .where(schemas.ResourcePoolORM.id == resource_pool_id)
                )
                stmt = delete(schemas.resource_pools_users).where(schemas.resource_pools_users.c.user_id.in_(sub))
                await session.execute(stmt)

    async def update_resource_class(
        self, resource_pool_id: int, resource_class_id: int, **kwargs
    ) -> models.ResourceClass:
        """Update a specific resource class."""
        async with self.session_maker() as session:
            async with session.begin():
                stmt = (
                    select(schemas.ResourceClassORM)
                    .where(schemas.ResourceClassORM.id == resource_class_id)  # type: ignore[arg-type]
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

    async def update_user(self, keycloak_id: int, username: str) -> models.User:
        """Update a specific user."""
        async with self.session_maker() as session:
            async with session.begin():
                stmt = (
                    update(schemas.UserORM)
                    .where(schemas.UserORM.keycloak_id == keycloak_id)
                    .values(username=username)
                    .returning(schemas.UserORM)
                )
                res = await session.execute(stmt)
                cls: Optional[schemas.UserORM] = res.scalars().first()
                if cls is None:
                    raise errors.MissingResourceError(message=f"The user with keycloak id {keycloak_id} does not exist")
                return cls.dump()
