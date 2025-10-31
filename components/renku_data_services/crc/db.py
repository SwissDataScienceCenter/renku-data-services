"""Adapter based on SQLAlchemy.

These adapters currently do a few things (1) generate SQL queries, (2) apply resource access controls,
(3) fetch the SQL results and (4) format them into a workable representation. In the future and as the code
grows it is worth looking into separating this functionality into separate classes rather than having
it all in one place.
"""

from asyncio import gather
from collections.abc import AsyncGenerator, Callable, Collection, Coroutine, Sequence
from dataclasses import asdict, dataclass, field
from functools import wraps
from typing import Any, Concatenate, Optional, ParamSpec, TypeVar

from sqlalchemy import NullPool, delete, false, select, true
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import Select, and_, not_, or_
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.base_models import RESET
from renku_data_services.crc import models
from renku_data_services.crc import orm as schemas
from renku_data_services.crc.core import validate_resource_class_update, validate_resource_pool_update
from renku_data_services.crc.models import ClusterPatch, ClusterSettings, SavedClusterSettings, SessionProtocol
from renku_data_services.crc.orm import ClusterORM
from renku_data_services.k8s.db import QuotaRepository
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
                select(schemas.UserORM.no_default_access)
                .where(and_(schemas.UserORM.keycloak_id == api_user.id, schemas.UserORM.no_default_access == true()))
                .exists()
            )
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
                select(schemas.UserORM.no_default_access)
                .where(and_(schemas.UserORM.keycloak_id == api_user.id, schemas.UserORM.no_default_access == true()))
                .exists()
            )
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

    def __init__(self, session_maker: Callable[..., AsyncSession], quotas_repo: QuotaRepository):
        super().__init__(session_maker, quotas_repo)
        self.__cluster_repo = ClusterRepository(session_maker=self.session_maker)

    async def initialize(self, async_connection_url: str, rp: models.UnsavedResourcePool) -> None:
        """Add the default resource pool if it does not already exist."""
        engine = create_async_engine(async_connection_url, poolclass=NullPool)
        session_maker = async_sessionmaker(
            engine,
            expire_on_commit=True,
        )
        async with session_maker() as session, session.begin():
            stmt = select(schemas.ResourcePoolORM.default == true())
            res = await session.execute(stmt)
            default_rp = res.scalars().first()
            if default_rp is None:
                orm = schemas.ResourcePoolORM.from_unsaved_model(new_resource_pool=rp, quota=None, cluster=None)
                session.add(orm)

    async def get_resource_pools(
        self, api_user: base_models.APIUser, id: Optional[int] = None, name: Optional[str] = None
    ) -> list[models.ResourcePool]:
        """Get resource pools from database."""
        async with self.session_maker() as session:
            stmt = (
                select(schemas.ResourcePoolORM)
                .options(selectinload(schemas.ResourcePoolORM.classes))
                .options(selectinload(schemas.ResourcePoolORM.cluster))
            )
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

    async def get_resource_pool_from_class(
        self, api_user: base_models.APIUser, resource_class_id: int
    ) -> models.ResourcePool:
        """Get the resource pool the class belongs to."""
        async with self.session_maker() as session:
            stmt = (
                select(schemas.ResourcePoolORM)
                .where(schemas.ResourcePoolORM.classes.any(schemas.ResourceClassORM.id == resource_class_id))
                .options(selectinload(schemas.ResourcePoolORM.classes))
                .options(selectinload(schemas.ResourcePoolORM.cluster))
            )
            # NOTE: The line below ensures that the right users can access the right resources, do not remove.
            stmt = _resource_pool_access_control(api_user, stmt)
            res = await session.execute(stmt)
            orm = res.scalar()
            if orm is None:
                raise errors.MissingResourceError(
                    message=f"Could not find the resource pool where a class with ID {resource_class_id} exists."
                )
            quota = self.quotas_repo.get_quota(orm.quota) if orm.quota else None
            return orm.dump(quota)

    async def get_default_resource_pool(self) -> models.ResourcePool:
        """Get the default resource pool."""
        async with self.session_maker() as session:
            stmt = (
                select(schemas.ResourcePoolORM)
                .where(schemas.ResourcePoolORM.default == true())
                .options(selectinload(schemas.ResourcePoolORM.classes))
            )
            res = await session.scalar(stmt)
            if res is None:
                raise errors.ProgrammingError(
                    message="Could not find the default resource pool, but this has to exist."
                )
            quota = self.quotas_repo.get_quota(res.quota) if res.quota else None
            return res.dump(quota)

    async def get_default_resource_class(self) -> models.ResourceClass:
        """Get the default resource class in the default resource pool."""
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
        """Get resource pools from database with indication of which resource class matches the specified criteria."""
        async with self.session_maker() as session:
            criteria = models.UnsavedResourceClass(
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
                .distinct()
                .options(selectinload(schemas.ResourcePoolORM.classes))
                .order_by(
                    schemas.ResourcePoolORM.id,
                    schemas.ResourcePoolORM.name,
                )
            )
            # NOTE: The line below ensures that the right users can access the right resources, do not remove.
            stmt = _resource_pool_access_control(api_user, stmt)
            res = await session.execute(stmt)
            return [
                i.dump(quota=self.quotas_repo.get_quota(i.quota), class_match_criteria=criteria)
                for i in res.scalars().all()
            ]

    @_only_admins
    async def insert_resource_pool(
        self, api_user: base_models.APIUser, new_resource_pool: models.UnsavedResourcePool
    ) -> models.ResourcePool:
        """Insert resource pool into database."""

        cluster = None
        if new_resource_pool.cluster_id:
            cluster = await self.__cluster_repo.select(cluster_id=new_resource_pool.cluster_id)

        quota = None
        if new_resource_pool.quota is not None:
            quota = self.quotas_repo.create_quota(new_quota=new_resource_pool.quota)

        async with self.session_maker() as session, session.begin():
            resource_pool = schemas.ResourcePoolORM.from_unsaved_model(
                new_resource_pool=new_resource_pool, quota=quota, cluster=cluster
            )
            if resource_pool.default:
                stmt = select(schemas.ResourcePoolORM).where(schemas.ResourcePoolORM.default == true())
                res = await session.execute(stmt)
                default_rps = res.unique().scalars().all()
                if len(default_rps) >= 1:
                    raise errors.ValidationError(
                        message="There can only be one default resource pool and one already exists."
                    )

            session.add(resource_pool)
            await session.flush()
            await session.refresh(resource_pool)
            return resource_pool.dump(quota=quota)

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

    async def get_resource_class(self, api_user: base_models.APIUser, id: int) -> models.ResourceClass:
        """Get a specific resource class by its ID."""
        classes = await self.get_classes(api_user, id)
        if len(classes) == 0:
            raise errors.MissingResourceError(message=f"The resource class with ID {id} cannot be found")
        return classes[0]

    @_only_admins
    async def insert_resource_class(
        self,
        api_user: base_models.APIUser,
        new_resource_class: models.UnsavedResourceClass,
        *,
        resource_pool_id: Optional[int] = None,
    ) -> models.ResourceClass:
        """Insert a resource class in the database."""
        async with self.session_maker() as session, session.begin():
            resource_class = schemas.ResourceClassORM.from_unsaved_model(
                new_resource_class=new_resource_class, resource_pool_id=resource_pool_id
            )
            print(f"resource_class = {resource_class.resource_pool_id}")

            if resource_pool_id is not None:
                stmt = select(schemas.ResourcePoolORM).where(schemas.ResourcePoolORM.id == resource_pool_id)
                res = await session.execute(stmt)
                rp = res.scalars().first()
                if rp is None:
                    raise errors.MissingResourceError(
                        message=f"Resource pool with id {resource_pool_id} does not exist."
                    )
                resource_class.resource_pool = rp
                if resource_class.default and len(rp.classes) > 0 and any([icls.default for icls in rp.classes]):
                    raise errors.ValidationError(
                        message="There can only be one default resource class per resource pool."
                    )
                quota = self.quotas_repo.get_quota(rp.quota) if rp.quota else None
                if quota and not quota.is_resource_class_compatible(new_resource_class):
                    raise errors.ValidationError(
                        message="The resource class {resource_class} is not compatible with the quota {quota}."
                    )

            session.add(resource_class)
            await session.flush()
            await session.refresh(resource_class)
            return resource_class.dump()

    @_only_admins
    async def update_resource_pool(
        self, api_user: base_models.APIUser, resource_pool_id: int, update: models.ResourcePoolPatch
    ) -> models.ResourcePool:
        """Update an existing resource pool in the database."""
        async with self.session_maker() as session, session.begin():
            stmt = (
                select(schemas.ResourcePoolORM)
                .where(schemas.ResourcePoolORM.id == resource_pool_id)
                .options(selectinload(schemas.ResourcePoolORM.classes))
            )
            res = await session.scalars(stmt)
            rp = res.one_or_none()
            if rp is None:
                raise errors.MissingResourceError(message=f"Resource pool with id {resource_pool_id} cannot be found")
            quota = self.quotas_repo.get_quota(rp.quota) if rp.quota else None

            validate_resource_pool_update(existing=rp.dump(quota=quota), update=update)

            if update.name is not None:
                rp.name = update.name
            if update.public is not None:
                rp.public = update.public
            if update.default is not None:
                rp.default = update.default
            if update.idle_threshold == 0:
                # Using "0" removes the value
                rp.idle_threshold = None
            elif update.idle_threshold is not None:
                rp.idle_threshold = update.idle_threshold
            if update.hibernation_threshold == 0:
                # Using "0" removes the value
                rp.hibernation_threshold = None
            elif update.hibernation_threshold is not None:
                rp.hibernation_threshold = update.hibernation_threshold

            if update.cluster_id is RESET:
                rp.cluster_id = None
            elif isinstance(update.cluster_id, ULID):
                cluster = await self.__cluster_repo.select(update.cluster_id)
                rp.cluster_id = cluster.id

            if update.quota is RESET and rp.quota:
                # Remove the existing quota
                self.quotas_repo.delete_quota(name=rp.quota)
            elif isinstance(update.quota, models.QuotaPatch) and rp.quota is None:
                # Create a new quota, the `update.quota` object has already been validated
                assert update.quota.cpu is not None
                assert update.quota.memory is not None
                assert update.quota.gpu is not None
                new_quota = models.UnsavedQuota(
                    cpu=update.quota.cpu,
                    memory=update.quota.memory,
                    gpu=update.quota.gpu,
                )
                quota = self.quotas_repo.create_quota(new_quota=new_quota)
                rp.quota = quota.id
            elif isinstance(update.quota, models.QuotaPatch):
                assert rp.quota is not None
                assert quota is not None
                # Update the existing quota
                updated_quota = models.Quota(
                    cpu=update.quota.cpu if update.quota.cpu is not None else quota.cpu,
                    memory=update.quota.memory if update.quota.memory is not None else quota.memory,
                    gpu=update.quota.gpu if update.quota.gpu is not None else quota.gpu,
                    gpu_kind=update.quota.gpu_kind if update.quota.gpu_kind is not None else quota.gpu_kind,
                    id=quota.id,
                )
                quota = self.quotas_repo.update_quota(quota=updated_quota)
                rp.quota = quota.id

            new_classes_coroutines = []
            if update.classes is not None:
                for rc in update.classes:
                    new_classes_coroutines.append(
                        self.update_resource_class(
                            api_user=api_user, resource_pool_id=resource_pool_id, resource_class_id=rc.id, update=rc
                        )
                    )

            if update.remote is RESET:
                rp.remote_provider_id = None
                rp.remote_json = None
            elif isinstance(update.remote, models.RemoteConfigurationFirecrestPatch):
                rp.remote_provider_id = (
                    update.remote.provider_id if update.remote.provider_id is not None else rp.remote_provider_id
                )
                remote_json = rp.remote_json if rp.remote_json is not None else dict()
                remote_json.update(update.remote.to_dict())
                del remote_json["provider_id"]
                rp.remote_json = remote_json

            await gather(*new_classes_coroutines)
            await session.flush()
            await session.refresh(rp)
            return rp.dump(quota=quota)

    @_only_admins
    async def delete_resource_pool(self, api_user: base_models.APIUser, id: int) -> None:
        """Delete a resource pool from the database."""
        async with self.session_maker() as session, session.begin():
            stmt = select(schemas.ResourcePoolORM).where(schemas.ResourcePoolORM.id == id)
            res = await session.execute(stmt)
            rp = res.scalars().first()
            if rp is not None:
                if rp.default:
                    raise errors.ValidationError(message="The default resource pool cannot be deleted.")
                await session.delete(rp)
                if rp.quota:
                    self.quotas_repo.delete_quota(rp.quota)
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
        self,
        api_user: base_models.APIUser,
        resource_pool_id: int,
        resource_class_id: int,
        update: models.ResourceClassPatch,
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
            res = await session.scalars(stmt)
            cls = res.one_or_none()
            if cls is None:
                raise errors.MissingResourceError(
                    message=(
                        f"The resource class with id {resource_class_id} does not exist, the resource pool with "
                        f"id {resource_pool_id} does not exist or the requested resource class is not "
                        "associated with the resource pool"
                    )
                )

            validate_resource_class_update(existing=cls.dump(), update=update)

            # NOTE: updating the 'default' field is not supported, so it is skipped below
            if update.name is not None:
                cls.name = update.name
            if update.cpu is not None:
                cls.cpu = update.cpu
            if update.memory is not None:
                cls.memory = update.memory
            if update.max_storage is not None:
                cls.max_storage = update.max_storage
            if update.gpu is not None:
                cls.gpu = update.gpu
            if update.default_storage is not None:
                cls.default_storage = update.default_storage

            if update.node_affinities is not None:
                existing_affinities: dict[str, schemas.NodeAffintyORM] = {i.key: i for i in cls.node_affinities}
                new_affinities: dict[str, schemas.NodeAffintyORM] = {
                    i.key: schemas.NodeAffintyORM(
                        key=i.key,
                        required_during_scheduling=i.required_during_scheduling,
                    )
                    for i in update.node_affinities
                }
                for new_affinity_key, new_affinity in new_affinities.items():
                    if new_affinity_key in existing_affinities:
                        # UPDATE existing affinity
                        existing_affinity = existing_affinities[new_affinity_key]
                        if new_affinity.required_during_scheduling != existing_affinity.required_during_scheduling:
                            existing_affinity.required_during_scheduling = new_affinity.required_during_scheduling
                    else:
                        # CREATE a brand new affinity
                        cls.node_affinities.append(new_affinity)
                # REMOVE an affinity
                for existing_affinity_key, existing_affinity in existing_affinities.items():
                    if existing_affinity_key not in new_affinities:
                        cls.node_affinities.remove(existing_affinity)

            if update.tolerations is not None:
                # existing_tolerations: dict[str, schemas.TolerationORM] = {tol.key: tol for tol in cls.tolerations}
                # new_tolerations: dict[str, schemas.TolerationORM] = {
                #     tol: schemas.TolerationORM(key=tol) for tol in update.tolerations
                # }
                # for new_tol_key, new_tol in new_tolerations.items():
                #     if new_tol_key not in existing_tolerations:
                #         # CREATE a brand new toleration
                #         cls.tolerations.append(new_tol)
                # # REMOVE a toleration
                # for existing_tol_key, existing_tol in existing_tolerations.items():
                #     if existing_tol_key not in new_tolerations:
                #         cls.tolerations.remove(existing_tol)

                # NOTE: the whole list of tolerations is updated
                existing_tolerations = list(cls.new_tolerations)
                for existing_tol, new_tol in zip(existing_tolerations, update.tolerations, strict=False):
                    existing_tol.contents = new_tol.to_dict()

                if len(update.tolerations) > len(existing_tolerations):
                    # Add new tolerations
                    for new_tol in update.tolerations[len(existing_tolerations) :]:
                        cls.new_tolerations.append(schemas.NewTolerationORM.from_model(new_tol))
                elif len(update.tolerations) < len(existing_tolerations):
                    # Remove old tolerations
                    cls.new_tolerations = cls.new_tolerations[: len(update.tolerations)]

            # NOTE: do we need to perform this check?
            if cls.resource_pool is None:
                raise errors.BaseError(
                    message="Unexpected internal error.",
                    detail=f"The resource class {resource_class_id} is not associated with any resource pool.",
                )

            await session.flush()
            await session.refresh(cls)

            cls_model = cls.dump()
            quota = self.quotas_repo.get_quota(cls_model.quota) if cls_model.quota else None
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

    async def get_quota(self, api_user: base_models.APIUser, resource_pool_id: int) -> models.Quota:
        """Get the quota of a resource pool."""
        rps = await self.get_resource_pools(api_user=api_user, id=resource_pool_id)
        if len(rps) < 1:
            raise errors.MissingResourceError(message=f"Cannot find the resource pool with ID {resource_pool_id}.")
        rp = rps[0]
        if rp.quota is None:
            raise errors.MissingResourceError(
                message=f"The resource pool with ID {resource_pool_id} does not have a quota."
            )
        return rp.quota

    @_only_admins
    async def update_quota(
        self,
        api_user: base_models.APIUser,
        resource_pool_id: int,
        update: models.QuotaPatch,
        quota_put_id: str | None = None,
    ) -> models.Quota:
        """Update the quota of a resource pool."""
        rps = await self.get_resource_pools(api_user=api_user, id=resource_pool_id)
        if len(rps) < 1:
            raise errors.MissingResourceError(message=f"Cannot find the resource pool with ID {resource_pool_id}.")
        rp = rps[0]
        if rp.quota is None:
            raise errors.MissingResourceError(
                message=f"The resource pool with ID {resource_pool_id} does not have a quota."
            )
        old_quota = rp.quota
        new_quota = models.Quota(
            cpu=update.cpu if update.cpu is not None else old_quota.cpu,
            memory=update.memory if update.memory is not None else old_quota.memory,
            gpu=update.gpu if update.gpu is not None else old_quota.gpu,
            gpu_kind=update.gpu_kind if update.gpu_kind is not None else old_quota.gpu_kind,
            id=quota_put_id or old_quota.id,
        )
        if new_quota.id != old_quota.id:
            raise errors.ValidationError(message="The 'id' field of a quota is immutable.")

        for rc in rp.classes:
            if not new_quota.is_resource_class_compatible(rc):
                raise errors.ValidationError(
                    message=f"The quota {new_quota} is not compatible with the resource class {rc}."
                )

        return self.quotas_repo.update_quota(quota=new_quota)


@dataclass
class Respository2Users:
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
    ) -> Respository2Users:
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
                        schemas.UserORM.keycloak_id == keycloak_id,
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
                    await session.execute(select(schemas.UserORM).where(schemas.UserORM.keycloak_id == keycloak_id))
                ).scalar_one_or_none()
                specific_user = None if not specific_user_res else specific_user_res.dump()
            allowed: list[base_models.User] = []
            disallowed: list[base_models.User] = []
            if rp.default:
                disallowed_stmt = select(schemas.UserORM).where(schemas.UserORM.no_default_access == true())
                if keycloak_id:
                    disallowed_stmt = disallowed_stmt.where(schemas.UserORM.keycloak_id == keycloak_id)
                disallowed_res = await session.execute(disallowed_stmt)
                disallowed = [user.dump() for user in disallowed_res.scalars().all()]
                if specific_user and specific_user not in disallowed:
                    allowed = [specific_user]
            elif rp.public and not rp.default:
                if specific_user:
                    allowed = [specific_user]
            elif not rp.public and not rp.default:
                allowed = [user.dump() for user in rp.users]
            return Respository2Users(rp.id, allowed, disallowed)

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
                select(schemas.UserORM)
                .where(schemas.UserORM.keycloak_id == keycloak_id)
                .options(selectinload(schemas.UserORM.resource_pools))
            )
            res = await session.execute(stmt)
            user = res.scalars().first()
            if user is None:
                user = schemas.UserORM(keycloak_id=keycloak_id)
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
                select(schemas.UserORM.id)
                .join(schemas.ResourcePoolORM, schemas.UserORM.resource_pools)
                .where(schemas.UserORM.keycloak_id == keycloak_id)
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
            stmt_usr = select(schemas.UserORM).where(schemas.UserORM.keycloak_id.in_(user_ids))
            res_usr = await session.execute(stmt_usr)
            users_to_add_exist = res_usr.scalars().all()
            user_ids_to_add_exist = [i.keycloak_id for i in users_to_add_exist]
            users_to_add_missing = [
                schemas.UserORM(keycloak_id=user_id) for user_id in user_ids if user_id not in user_ids_to_add_exist
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
            stmt = select(schemas.UserORM).where(schemas.UserORM.keycloak_id == keycloak_id)
            res = await session.execute(stmt)
            user: Optional[schemas.UserORM] = res.scalars().first()
            if not user:
                user = schemas.UserORM(keycloak_id=keycloak_id)
                session.add(user)
            allowed_updates = {"no_default_access"}
            if not set(kwargs.keys()).issubset(allowed_updates):
                raise errors.ValidationError(
                    message=f"Only the following fields {allowed_updates} can be updated for a resource pool user.."
                )
            if (no_default_access := kwargs.get("no_default_access")) is not None:
                user.no_default_access = no_default_access
            return user.dump()


@dataclass
class ClusterRepository:
    """Repository for cluster configurations."""

    session_maker: Callable[..., AsyncSession]

    async def select_all(self, cluster_id: ULID | None = None) -> AsyncGenerator[SavedClusterSettings, Any]:
        """Get cluster configurations from the database."""
        async with self.session_maker() as session:
            query = select(ClusterORM)
            if cluster_id is not None:
                query = query.where(ClusterORM.id == cluster_id)

            clusters = await session.stream_scalars(query)
            async for cluster in clusters:
                yield cluster.dump()

    async def select(self, cluster_id: ULID) -> SavedClusterSettings:
        """Get cluster configurations from the database."""
        async for cluster in self.select_all(cluster_id):
            return cluster

        raise errors.MissingResourceError(message=f"Cluster definition id='{cluster_id}' does not exist.")

    @_only_admins
    async def insert(self, api_user: base_models.APIUser, cluster: ClusterSettings) -> ClusterSettings:
        """Creates a new cluster configuration."""

        cluster_orm = ClusterORM.load(cluster)
        async with self.session_maker() as session, session.begin():
            session.add(cluster_orm)
            await session.flush()
            await session.refresh(cluster_orm)

            return cluster_orm.dump()

    @_only_admins
    async def update(self, api_user: base_models.APIUser, cluster: ClusterPatch, cluster_id: ULID) -> ClusterSettings:
        """Updates a cluster configuration."""

        async with self.session_maker() as session, session.begin():
            saved_cluster = (await session.scalars(select(ClusterORM).where(ClusterORM.id == cluster_id))).one_or_none()
            if saved_cluster is None:
                raise errors.MissingResourceError(message=f"Cluster definition id='{cluster_id}' does not exist.")

            for key, value in asdict(cluster).items():
                match key, value:
                    case "session_protocol", SessionProtocol():
                        setattr(saved_cluster, key, value.value)
                    case "session_storage_class", "":
                        # If we received an empty string in the storage class, reset it to the default storage class by
                        # setting it to None.
                        setattr(saved_cluster, key, None)
                    case "service_account_name", "":
                        # If we received an empty string in the service account name, set it back to None.
                        setattr(saved_cluster, key, None)
                    case _, None:
                        # Do not modify a value which has not been set in the patch
                        pass
                    case _, _:
                        setattr(saved_cluster, key, value)

            await session.flush()
            await session.refresh(saved_cluster)

            return saved_cluster.dump()

    @_only_admins
    async def delete(self, api_user: base_models.APIUser, cluster_id: ULID) -> None:
        """Get cluster configurations from the database."""

        async with self.session_maker() as session, session.begin():
            r = await session.scalars(select(ClusterORM).where(ClusterORM.id == cluster_id))
            cluster = r.one_or_none()
            if cluster is not None:
                await session.delete(cluster)
