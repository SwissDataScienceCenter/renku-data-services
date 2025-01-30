from typing import Any
from pydantic import BaseModel
import pytest
from renku_data_services.solr.solr_client import DefaultSolrClient, UpsertSuccess


class Project(BaseModel):
    id: str
    name: str

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


@pytest.mark.asyncio
async def test_solr_client(solr_search):
    async with DefaultSolrClient(solr_search) as client:
        p = Project(id="p1", name="my project")
        r1 = await client.upsert([p])
        match r1:
            case UpsertSuccess() as s:
                assert s.header.status == 0
                assert s.header.queryTime > 0
            case _:
                raise Exception(f"Unexpected result: {r1}")

        qr = await client.get("p1")
        assert qr.responseHeader.status == 200
        assert qr.response.numFound == 1
        assert len(qr.response.docs) == 1

        doc = Project.model_validate(qr.response.docs[0])
        assert doc.id == "p1"
        assert doc.name == "my project"

        print(doc)
