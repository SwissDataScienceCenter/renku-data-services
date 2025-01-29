"""Some testing."""

import asyncio
import logging
from typing import Any

from pydantic import BaseModel
import pydantic
from renku_data_services.solr import entity_schema
from renku_data_services.solr.solr_migrate import SchemaMigrator
from renku_data_services.solr.solr_schema import (
    Analyzer,
    DeleteFieldCommand,
    Field,
    FieldName,
    FieldType,
    ReplaceCommand,
    Tokenizers,
    TypeName,
    CopyFieldRule,
    AddCommand,
    SchemaCommandList,
    FieldTypeClasses,
    Filters,
    Tokenizer,
)

from renku_data_services.solr.solr_client import (
    DefaultSolrClient,
    DocVersion,
    SolrClientConfig,
    SolrDocument,
    SolrQuery,
)

logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)


class ProjectDoc(BaseModel):
    """A solr document representing a project."""

    id: str
    name: str
    version: int = pydantic.Field(serialization_alias="_version_")

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True)


async def _test_schema():
    cfg = SolrClientConfig(base_url="http://rsdevcnt:8983", core="renku-search-dev", user=None)
    async with DefaultSolrClient(cfg) as client:
        r = await client.modify_schema(
            SchemaCommandList(
                [
                    ReplaceCommand(FieldType(name=TypeName("content_all"), clazz=FieldTypeClasses.type_text)),
                    ReplaceCommand(FieldType(name=TypeName("content_my"), clazz=FieldTypeClasses.type_text)),
                ]
            )
        )
        print(r.raise_for_status().json())


async def _test_upsert():
    cfg = SolrClientConfig(base_url="http://rsdevcnt:8983", core="renku-search-dev", user=None)
    async with DefaultSolrClient(cfg) as client:
        mydoc = ProjectDoc(id="p123", name="my project", version=DocVersion.exact(15654))
        res = await client.upsert([mydoc])
        print(res)


async def _test_get_schema():
    cfg = SolrClientConfig(base_url="http://rsdevcnt:8983", core="renku-search-dev", user=None)
    async with DefaultSolrClient(cfg) as client:
        cs = await client.get_schema()
        print(cs)


async def _test_query():
    cfg = SolrClientConfig(base_url="http://rsdevcnt:8983", core="renku-search-dev", user=None)
    async with DefaultSolrClient(cfg) as client:
        r = await client.query(SolrQuery.query_all("*:*"))
        print(r)


async def _test_migrator_get_version():
    cfg = SolrClientConfig(base_url="http://rsdevcnt:8983", core="renku-search-dev", user=None)
    migrator = SchemaMigrator(cfg)
    r = await migrator.current_version()
    print(r)


async def _test0():
    tokenizer = Tokenizer(name=TypeName("classic"))
    filter = Filters.edgeNgram()
    analyzer = Analyzer(tokenizer=tokenizer, filters=[filter, Filters.ascii_folding])
    ftype = FieldType(name=TypeName("project_name_type"), clazz=FieldTypeClasses.type_str, indexed=True)
    field = Field(name=FieldName("project_name"), type=ftype.name, indexed=True)
    print(field.to_json())


async def _test2():
    tokenizer = Tokenizers.uax29UrlEmail
    filter = Filters.ngram
    analyzer = Analyzer(tokenizer=tokenizer, filters=[filter])
    ft = FieldType(name=TypeName("name_s"), clazz=FieldTypeClasses.type_text, index_analyzer=analyzer)
    field = Field.of(name=FieldName("project_name"), type=ft)
    field.required = True
    field.indexed = True
    field.multiValued = True
    cmds = SchemaCommandList(
        [
            AddCommand(ft),
            AddCommand(CopyFieldRule(source=FieldName("other_name_s"), dest=FieldName("target_name_s"))),
            AddCommand(field),
            AddCommand(Field.of(name=FieldName("user_name"), type=ft)),
            ReplaceCommand(ft),
            DeleteFieldCommand(FieldName("user_n_s")),
        ]
    )
    print(cmds.to_json())


async def _test_entity_schema():
    cfg = SolrClientConfig(base_url="http://rsdevcnt:8983", core="renku-search-dev", user=None)
    migrator = SchemaMigrator(cfg)
    r = await migrator.migrate(entity_schema.all_migrations)
    print(r)

if __name__ == "__main__":
    asyncio.run(_test_entity_schema())
