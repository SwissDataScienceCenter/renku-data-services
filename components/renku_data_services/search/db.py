"""Database operations for search."""

import json
from collections.abc import Callable
from datetime import datetime
from textwrap import dedent
from typing import Any, cast

from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from renku_data_services.base_models.core import Slug
from renku_data_services.data_connectors.models import DataConnector, GlobalDataConnector
from renku_data_services.namespace.models import Group
from renku_data_services.project.models import Project
from renku_data_services.search.models import DeleteDoc, Entity
from renku_data_services.search.orm import RecordState, SearchUpdatesORM
from renku_data_services.solr.entity_documents import DataConnector as DataConnectorDoc
from renku_data_services.solr.entity_documents import Group as GroupDoc
from renku_data_services.solr.entity_documents import Project as ProjectDoc
from renku_data_services.solr.entity_documents import User as UserDoc
from renku_data_services.solr.solr_client import DocVersions
from renku_data_services.users.models import UserInfo


def _user_to_entity_doc(user: UserInfo) -> UserDoc:
    return UserDoc(
        path=user.namespace.path.serialize(),
        slug=user.namespace.path.first,
        id=user.id,
        firstName=user.first_name,
        lastName=user.last_name,
        version=DocVersions.off(),
    )


def _group_to_entity_doc(group: Group) -> GroupDoc:
    return GroupDoc(
        path=group.slug,
        slug=Slug(group.slug),
        id=group.id,
        name=group.name,
        description=group.description,
        version=DocVersions.off(),
    )


def _project_to_entity_doc(p: Project) -> ProjectDoc:
    return ProjectDoc(
        namespace_path=p.namespace.path.serialize(),
        path=p.path.serialize(),
        id=p.id,
        name=p.name,
        slug=Slug.from_name(p.slug),
        visibility=p.visibility,
        createdBy=p.created_by,
        creationDate=p.creation_date,
        repositories=p.repositories,
        description=p.description,
        keywords=p.keywords if p.keywords is not None else [],
        version=DocVersions.off(),
    )


def _dataconnector_to_entity_doc(dc: DataConnector | GlobalDataConnector) -> DataConnectorDoc:
    ns = dc.namespace.path.serialize() if isinstance(dc, DataConnector) else None
    pt = dc.path.serialize() if isinstance(dc, DataConnector) else dc.slug
    return DataConnectorDoc(
        id=dc.id,
        path=pt,
        name=dc.name,
        storageType=dc.storage.storage_type,
        readonly=dc.storage.readonly,
        slug=Slug.from_name(dc.slug),
        visibility=dc.visibility,
        createdBy=dc.created_by,
        creationDate=dc.creation_date,
        namespace_path=ns,
        description=dc.description,
        keywords=dc.keywords if dc.keywords is not None else [],
        version=DocVersions.off(),
        doi=dc.doi if hasattr(dc, "doi") else None,
        publisherName=dc.publisher_name if hasattr(dc, "publisher_name") else None,
    )


class SearchUpdatesRepo:
    """Db operations for the search updates table.

    NOTE: This does not apply any authentication or authorization to calls.
    """

    def __init__(self, session_maker: Callable[..., AsyncSession]) -> None:
        self.session_maker = session_maker

    async def find_by_id(self, id: ULID) -> SearchUpdatesORM | None:
        """Find a row by its primary key."""
        async with self.session_maker() as session:
            return await session.get(SearchUpdatesORM, id)

    def __make_params(self, entity: Entity, started: datetime) -> dict[str, Any]:
        match entity:
            case Group() as g:
                dg = _group_to_entity_doc(g)
                return {
                    "entity_id": str(dg.id),
                    "entity_type": "Group",
                    "created_at": started,
                    "payload": json.dumps(dg.to_dict()),
                }

            case UserInfo() as u:
                du = _user_to_entity_doc(u)
                return {
                    "entity_id": du.id,
                    "entity_type": "User",
                    "created_at": started,
                    "payload": json.dumps(du.to_dict()),
                }

            case Project() as p:
                dp = _project_to_entity_doc(p)
                return {
                    "entity_id": str(dp.id),
                    "entity_type": "Project",
                    "created_at": started,
                    "payload": json.dumps(dp.to_dict()),
                }

            case DataConnector() as d:
                dc = _dataconnector_to_entity_doc(d)
                return {
                    "entity_id": str(dc.id),
                    "entity_type": "DataConnector",
                    "created_at": started,
                    "payload": json.dumps(dc.to_dict()),
                }

            case GlobalDataConnector() as d:
                dc = _dataconnector_to_entity_doc(d)
                return {
                    "entity_id": str(dc.id),
                    "entity_type": "DataConnector",
                    "created_at": started,
                    "payload": json.dumps(dc.to_dict()),
                }

            case DeleteDoc() as d:
                return {
                    "entity_id": d.id,
                    "entity_type": d.entity_type,
                    "created_at": started,
                    "payload": json.dumps(d.to_dict()),
                }

    async def upsert(self, entity: Entity, started_at: datetime | None = None) -> ULID:
        """Add entity documents to the staging table.

        If an entity with same id already exists, it is updated.
        """
        started = started_at if started_at is not None else datetime.now()
        params = self.__make_params(entity, started)
        async with self.session_maker() as session, session.begin():
            result = await session.execute(
                text(
                    dedent("""\
                  WITH new_user AS (
                    INSERT INTO events.search_updates
                      (entity_id, entity_type, created_at, payload)
                    VALUES
                      (:entity_id, :entity_type, :created_at, :payload)
                    ON CONFLICT ("entity_id") DO UPDATE
                    SET created_at = :created_at, payload = :payload
                    RETURNING id
                  ) SELECT * from new_user UNION
                    SELECT id FROM events.search_updates WHERE entity_id = :entity_id AND entity_type = :entity_type
                """)
                ),
                params,
            )
            await session.commit()
            el = result.first()
            if el is None:
                raise Exception(f"Inserting {entity} did not result in returning an id.")
            return cast(ULID, ULID.from_str(el.id))  # huh? mypy wants this cast

    async def insert(self, entity: Entity, started_at: datetime | None) -> ULID:
        """Insert a entity document into the staging table.

        Do nothing if it already exists.
        """
        started = started_at if started_at is not None else datetime.now()
        params = self.__make_params(entity, started)
        async with self.session_maker() as session, session.begin():
            result = await session.execute(
                text(
                    dedent("""
                  WITH new_entity AS (
                    INSERT INTO events.search_updates
                      (entity_id, entity_type, created_at, payload)
                    VALUES
                      (:entity_id, :entity_type, :created_at, :payload)
                    ON CONFLICT ("entity_id") DO NOTHING
                    RETURNING id
                  ) SELECT * from new_entity UNION
                    SELECT id FROM events.search_updates WHERE entity_id = :entity_id AND entity_type = :entity_type
                """)
                ),
                params,
            )
            await session.commit()
            el = result.first()
            if el is None:
                raise Exception(f"Inserting {entity} did not result in returning an id.")
            return cast(ULID, ULID.from_str(el.id))

    async def clear_all(self) -> None:
        """Clears the staging table of all data."""
        async with self.session_maker() as session, session.begin():
            await session.execute(text("TRUNCATE TABLE events.search_updates"))
            return None

    async def select_next(self, size: int) -> list[SearchUpdatesORM]:
        """Select and mark the next records and return them in a list."""
        async with self.session_maker() as session, session.begin():
            stmt = (
                select(SearchUpdatesORM)
                .where(SearchUpdatesORM.state.is_(None))
                # lock retrieved rows, skip already locked ones, to deal with concurrency
                .with_for_update(skip_locked=True)
                .limit(size)
                .order_by(SearchUpdatesORM.id)
            )
            result = await session.scalars(stmt)
            records = result.all()
            for r in records:
                r.state = RecordState.Locked
                session.add(r)

            return list(records)

    async def __mark_rows(self, state: RecordState | None, ids: list[ULID]) -> None:
        """Mark rows with the given state."""
        async with self.session_maker() as session, session.begin():
            stmt = (
                update(SearchUpdatesORM)
                .where(SearchUpdatesORM.state == RecordState.Locked)
                .where(SearchUpdatesORM.id.in_(ids))
                .values(state=state)
            )
            await session.execute(stmt)

    async def mark_processed(self, ids: list[ULID]) -> None:
        """Remove processed rows."""
        async with self.session_maker() as session, session.begin():
            stmt = (
                delete(SearchUpdatesORM)
                .where(SearchUpdatesORM.state == RecordState.Locked)
                .where(SearchUpdatesORM.id.in_(ids))
            )
            await session.execute(stmt)

    async def mark_reset(self, ids: list[ULID]) -> None:
        """Mark these rows as open so they can be processed."""
        await self.__mark_rows(None, ids)

    async def mark_failed(self, ids: list[ULID]) -> None:
        """Marke these rows as failed."""
        await self.__mark_rows(RecordState.Failed, ids)

    async def reset_locked(self) -> None:
        """Resets all locked rows to open."""
        async with self.session_maker() as session, session.begin():
            stmt = update(SearchUpdatesORM).where(SearchUpdatesORM.state == RecordState.Locked).values(state=None)
            await session.execute(stmt)
