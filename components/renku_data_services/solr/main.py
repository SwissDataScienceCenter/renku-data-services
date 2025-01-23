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
    tokenizer = solr_schema.Tokenizer("classic")
    filter = solr_schema.Filter("mine_f", {})
    analyzer = solr_schema.Analyzer(tokenizer, [filter])
    print(analyzer.to_json())

if __name__ == "__main__":
    asyncio.run(_test2())
