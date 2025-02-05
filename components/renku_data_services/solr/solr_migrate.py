"""Manage solr schema migrations."""

import logging
from dataclasses import dataclass
from typing import Any, Self

import pydantic
from pydantic import AliasChoices, BaseModel

from renku_data_services.solr.solr_client import (
    DefaultSolrClient,
    DocVersion,
    DocVersions,
    SolrClientConfig,
)
from renku_data_services.solr.solr_schema import (
    AddCommand,
    CopyFieldRule,
    CoreSchema,
    DeleteDynamicFieldCommand,
    DeleteFieldCommand,
    DeleteFieldTypeCommand,
    DynamicFieldRule,
    Field,
    FieldType,
    ReplaceCommand,
    SchemaCommand,
    SchemaCommandList,
)


def _is_applied(schema: CoreSchema, cmd: SchemaCommand) -> bool:
    """Check whether a schema command is already applied to the given schema."""
    match cmd:
        case AddCommand(FieldType() as ft):
            return any(x.name == ft.name for x in schema.fieldTypes)

        case AddCommand(Field() as f):
            return any(x.name == f.name for x in schema.fields)

        case AddCommand(DynamicFieldRule() as f):
            return any(x.name == f.name for x in schema.dynamicFields)

        case AddCommand(CopyFieldRule() as f):
            return any(x.source == f.source and x.dest == f.dest for x in schema.copyFields)

        case DeleteFieldCommand(f):
            return all(x.name != f for x in schema.fields)

        case DeleteFieldTypeCommand(f):
            return all(x.name != f for x in schema.fieldTypes)

        case DeleteDynamicFieldCommand(f):
            return all(x.name != f for x in schema.dynamicFields)

        case ReplaceCommand(FieldType() as ft):
            return any(x == ft for x in schema.fieldTypes)

        case ReplaceCommand(Field() as f):
            return any(x == f for x in schema.fields)

        case _:
            return False


@dataclass
class SchemaMigration:
    """A migration consisting of the version and a set of schema commands."""

    version: int
    commands: list[SchemaCommand]
    requires_reindex: bool

    def is_empty(self) -> bool:
        """Return whether the migration contains any commands."""
        return self.commands == []

    def align_with(self, schema: CoreSchema) -> Self:
        """Aligns the list of schema commands to the given schema.

        Return a copy of this value, removing all schema commands that have already
        been applied to the given schema.
        """
        cmds = list(filter(lambda e: not (_is_applied(schema, e)), self.commands))
        return type(self)(version=self.version, commands=cmds, requires_reindex=self.requires_reindex)


@dataclass
class MigrateResult:
    """The overall result of running a set of migrations."""

    start_version: int | None
    end_version: int | None
    migrations_run: int
    migrations_skipped: int
    requires_reindex: bool

    @classmethod
    def empty(cls) -> "MigrateResult":
        """Create an empty MigrateResult."""
        return MigrateResult(None, None, 0, 0, False)


class VersionDoc(BaseModel):
    """A document tracking the schema migration.

    The field names correspond to solr dynamic fields. Since this is
    the document that gets inserted before any of our schema migration
    runs, it uses solr dynamic fields: Appending a `_<type-letter>` to
    a name to indicate the type of the field. So a `_b` is a bool and
    a `_l` is a long/int.
    """

    id: str
    current_schema_version_l: int
    migration_running_b: bool
    version: DocVersion = pydantic.Field(
        serialization_alias="_version_", validation_alias=AliasChoices("version", "_version_")
    )

    def to_dict(self) -> dict[str, Any]:
        """Return the dict representation of this document."""
        return self.model_dump(by_alias=True)


class MigrationState(BaseModel):
    """A private class tracking intermediate schema changes per migration."""

    solr_schema: CoreSchema
    doc: VersionDoc
    skipped_migrations: int


class SchemaMigrator:
    """Allows to inspect the current schema version and run schema migrations against a solr core."""

    def __init__(self, cfg: SolrClientConfig) -> None:
        self.__config = cfg
        self.__docId: str = "VERSION_ID_EB779C6B-1D96-47CB-B304-BECF15E4A607"

    async def current_version(self) -> int | None:
        """Return the current schema version."""
        async with DefaultSolrClient(self.__config) as client:
            doc = await self.__current_version0(client)
            if doc is None:
                return None
            else:
                return doc.current_schema_version_l

    async def __current_version0(self, client: DefaultSolrClient) -> VersionDoc | None:
        """Return the current schema version document."""
        resp = await client.get_raw(self.__docId)
        docs = resp.raise_for_status().json()["response"]["docs"]
        if docs == []:
            return None
        else:
            return VersionDoc.model_validate(docs[0])

    async def migrate(self, migrations: list[SchemaMigration]) -> MigrateResult:
        """Run all given migrations, skipping those that have been done before."""
        async with DefaultSolrClient(self.__config) as client:
            initialDoc = await self.__current_version0(client)
            if initialDoc is None:
                initialDoc = VersionDoc(
                    id=self.__docId,
                    current_schema_version_l=-1,
                    migration_running_b=False,
                    version=DocVersions.not_exists(),
                )
            return await self.__doMigrate(client, migrations, initialDoc)

    async def __doMigrate(
        self, client: DefaultSolrClient, migrations: list[SchemaMigration], initialDoc: VersionDoc
    ) -> MigrateResult:
        logging.info(
            f"Core {self.__config.core}: Found current schema version: "
            f"{initialDoc.current_schema_version_l} using {self.__docId}"
        )
        remain = [e for e in migrations if e.version > initialDoc.current_schema_version_l]
        logging.info(f"There are {len(remain)} migrations to run")
        if remain == []:
            return MigrateResult.empty()

        remain.sort(key=lambda m: m.version)
        schema = await client.get_schema()
        state = MigrationState(solr_schema=schema, doc=initialDoc, skipped_migrations=0)
        [finalState := await self.__applyMigration(client, state, x) for x in remain]
        return MigrateResult(
            start_version=initialDoc.current_schema_version_l,
            end_version=remain[-1].version,
            migrations_run=len(remain),
            migrations_skipped=finalState.skipped_migrations,
            requires_reindex=any(x.requires_reindex for x in remain),
        )

    async def __applyMigration(
        self, client: DefaultSolrClient, state: MigrationState, m: SchemaMigration
    ) -> MigrationState:
        cmds = m.align_with(state.solr_schema)
        if cmds.is_empty():
            logging.info(f"Migration {m.version} seems to be applied. Skipping it")
            v = await self.__upsert_version(client, state.doc, m.version)
            return state.model_copy(update={"skippedMigrations": state.skipped_migrations + 1, "doc": v})
        else:
            r = await client.modify_schema(SchemaCommandList(cmds.commands))
            r.raise_for_status()
            schema = await client.get_schema()
            doc = await self.__upsert_version(client, state.doc, m.version)
            return MigrationState(solr_schema=schema, doc=doc, skipped_migrations=state.skipped_migrations)

    async def __upsert_version(self, client: DefaultSolrClient, current: VersionDoc, next: int) -> VersionDoc:
        logging.info(f"core {self.__config.core}: set schema migration version to {next}")
        next_doc = current.model_copy(update={"current_schema_version_l": next})
        await client.upsert([next_doc])
        result = await client.get(self.__docId)
        return VersionDoc.model_validate(result.response.docs[0])
