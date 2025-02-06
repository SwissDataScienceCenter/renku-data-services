import pytest

from renku_data_services.base_models.core import Slug
from renku_data_services.solr.entity_documents import Group, Project, User
from renku_data_services.solr.entity_schema import Fields
from renku_data_services.solr.solr_client import (
    DefaultSolrClient,
    DocVersions,
    SolrQuery,
    SortDirection,
    UpsertResponse,
    UpsertSuccess,
)
from test.components.renku_data_services.solr import test_entity_documents


def assert_upsert_result(r: UpsertResponse):
    match r:
        case UpsertSuccess() as s:
            assert s.header.status == 0
            assert s.header.query_time > 0
        case _:
            raise Exception(f"Unexpected result: {r}")


def test_serialize_document():
    d = User(id="one", namespace=Slug("one"), version=DocVersions.not_exists())
    djson = '{"id":"one", "namespace":"one", "_version_": -1}'
    nd = User.model_validate_json(djson)
    assert nd == d


def test_serialize_solr_query():
    q1 = SolrQuery.query_all_fields("name:hello")
    assert q1.to_dict() == {"query": "name:hello", "fields": ["*", "score"], "sort": ""}

    q2 = SolrQuery.query_all_fields("name:hello").with_sort([(Fields.name, SortDirection.asc)])
    assert q2.to_dict() == {"query": "name:hello", "fields": ["*", "score"], "sort": "name asc"}

    q3 = SolrQuery.query_all_fields("name:hello").with_sort(
        [(Fields.name, SortDirection.asc), (Fields.creation_date, SortDirection.desc)]
    )
    assert q3.to_dict() == {"query": "name:hello", "fields": ["*", "score"], "sort": "name asc,creationDate desc"}


@pytest.mark.asyncio
async def test_insert_and_query_project(solr_search):
    async with DefaultSolrClient(solr_search) as client:
        p = test_entity_documents.project_ai_stuff
        r1 = await client.upsert([p])
        assert_upsert_result(r1)

        qr = await client.query(SolrQuery.query_all_fields(f"id:{str(p.id)}"))
        assert qr.responseHeader.status == 0
        assert qr.response.num_found == 1
        assert len(qr.response.docs) == 1

        doc = Project.model_validate(qr.response.docs[0])
        assert doc.id == p.id
        assert doc.name == p.name
        assert doc.score is not None
        assert doc.score > 0


@pytest.mark.asyncio
async def test_insert_and_query_user(solr_search):
    async with DefaultSolrClient(solr_search) as client:
        u1 = test_entity_documents.user_tadej_pogacar
        u2 = test_entity_documents.user_jan_ullrich
        r1 = await client.upsert([u1, u2])
        assert_upsert_result(r1)

        qr = await client.query(
            SolrQuery.query_all_fields("_type:User").with_sort([(Fields.first_name, SortDirection.asc)])
        )
        assert qr.responseHeader.status == 0
        assert qr.response.num_found == 2
        assert len(qr.response.docs) == 2

        su1 = User.from_dict(qr.response.docs[0])
        su2 = User.from_dict(qr.response.docs[1])
        assert su1.score is not None and su1.score > 0
        assert su2.score is not None and su2.score > 0
        assert su1.reset_solr_fields() == u2
        assert su2.reset_solr_fields() == u1


@pytest.mark.asyncio
async def test_insert_and_query_group(solr_search):
    async with DefaultSolrClient(solr_search) as client:
        g = test_entity_documents.group_team
        r1 = await client.upsert([g])
        assert_upsert_result(r1)

        qr = await client.query(SolrQuery.query_all_fields("_type:Group"))
        assert qr.responseHeader.status == 0
        assert qr.response.num_found == 1
        assert len(qr.response.docs) == 1

        sg = Group.from_dict(qr.response.docs[0])
        assert sg.score is not None and sg.score > 0
        assert sg.reset_solr_fields() == g
