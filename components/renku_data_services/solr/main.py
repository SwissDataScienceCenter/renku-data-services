"""Some testing."""

import asyncio
import logging

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

from renku_data_services.solr.solr_client import SolrClient, DefaultSolrClient, SolrClientConfig, SolrQuery

logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)


async def _test():
    cfg = SolrClientConfig(base_url="http://rsdevcnt:8983", core="renku-search-dev", user=None)
    async with DefaultSolrClient(cfg) as client:
        r = await client.modify_schema(
            SchemaCommandList(
                [ReplaceCommand(FieldType(name=TypeName("content_all"), clazz=FieldTypeClasses.type_text))]
            )
        )
        print(r.raise_for_status().json())


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


if __name__ == "__main__":
    asyncio.run(_test())
