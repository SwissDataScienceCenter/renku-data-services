"""Some testing."""

import asyncio
import logging

from renku_data_services.solr import solr_client, solr_schema

logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)


async def _test():
    client = await solr_client.DefaultSolrClient("http://rsdevcnt:8983/solr/renku-search-dev")
    doc = await client.query("*:*")
    await client.close()
    print(doc.docs)


async def _test2():
    tokenizer = solr_schema.Tokenizer(solr_schema.TypeName("classic"))
    filter = solr_schema.Filters.NGRAM
    analyzer = solr_schema.Analyzer(tokenizer, [filter])
    ft = solr_schema.FieldType(
        name=solr_schema.TypeName("name_s"), clazz=solr_schema.FieldTypeClasses.TYPE_TEXT, index_analyzer=analyzer
    )
    field = solr_schema.Field.of(name=solr_schema.FieldName("project_name"), type=ft)
    field.required = True
    field.indexed = True
    field.multiValued = True
    cmd = solr_schema.AddCommand(field)
    cmds = solr_schema.SchemaCommandList(
        [
            cmd,
            solr_schema.AddCommand(
                solr_schema.CopyFieldRule(solr_schema.FieldName("other_name_s"), solr_schema.FieldName("target_name_s"))
            ),
        ]
    )
    print(cmds.to_json())


if __name__ == "__main__":
    asyncio.run(_test2())
