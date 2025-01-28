"""Some testing."""

import asyncio
import logging

from renku_data_services.solr.solr_schema import (
    Analyzer,
    Field,
    FieldName,
    FieldType,
    TypeName,
    CopyFieldRule,
    AddCommand,
    SchemaCommandList,
    FieldTypeClasses,
    Filters,
    Tokenizer,
)

logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)


# async def _test():
#     client = await solr_client.DefaultSolrClient("http://rsdevcnt:8983/solr/renku-search-dev")
#     doc = await client.query("*:*")
#     await client.close()
#     print(doc.docs)


async def _test():
    tokenizer = Tokenizer(name=TypeName("classic"))
    filter = Filters.edgeNgram()
    analyzer = Analyzer(tokenizer=tokenizer, filters=[filter, Filters.ascii_folding])
    ftype = FieldType(name=TypeName("project_name_type"), clazz=FieldTypeClasses.type_str, indexed=True)
    field = Field(name=FieldName("project_name"), type=ftype.name, indexed=True)
    print(field.to_json())


async def _test2():
    tokenizer = Tokenizer(name=TypeName("classic"))
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
        ]
    )
    print(cmds.to_json())


if __name__ == "__main__":
    asyncio.run(_test2())
