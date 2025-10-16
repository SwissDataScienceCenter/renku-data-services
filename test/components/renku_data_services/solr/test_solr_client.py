import json
import random
import string

import pytest

from renku_data_services.solr.entity_documents import Group, Project, User
from renku_data_services.solr.entity_schema import Fields, FieldTypes
from renku_data_services.solr.solr_client import (
    DefaultSolrAdminClient,
    DefaultSolrClient,
    FacetArbitraryRange,
    FacetBuckets,
    FacetCount,
    FacetRange,
    FacetTerms,
    SolrBucketFacetResponse,
    SolrClientConfig,
    SolrClientCreateCoreException,
    SolrFacets,
    SolrQuery,
    SortDirection,
    SubQuery,
    UpsertResponse,
    UpsertSuccess,
)
from renku_data_services.solr.solr_schema import AddCommand, Field, FieldName, SchemaCommandList
from test.components.renku_data_services.solr import test_entity_documents


def assert_upsert_result(r: UpsertResponse):
    match r:
        case UpsertSuccess() as s:
            assert s.header.status == 0
            assert s.header.query_time > 0
        case _:
            raise Exception(f"Unexpected result: {r}")


def test_facet_terms() -> None:
    ft = FacetTerms(name=FieldName("types"), field=Fields.entity_type)
    assert ft.to_dict() == {
        "types": {
            "type": "terms",
            "field": "_type",
            "missing": False,
            "numBuckets": False,
            "allBuckets": False,
        }
    }
    ft = FacetTerms(name=FieldName("cat"), field=FieldName("category"), limit=100)
    assert ft.to_dict() == {
        "cat": {
            "type": "terms",
            "field": "category",
            "limit": 100,
            "missing": False,
            "numBuckets": False,
            "allBuckets": False,
        }
    }


def test_facet_range() -> None:
    fr = FacetArbitraryRange(
        name=FieldName("stars"),
        field=FieldName("stars"),
        ranges=[FacetRange(start="*", to=100), FacetRange(start=100, to=200), FacetRange(start=200, to="*")],
    )
    assert fr.to_dict() == {
        "stars": {
            "type": "range",
            "field": "stars",
            "ranges": [{"from": "*", "to": 100}, {"from": 100, "to": 200}, {"from": 200, "to": "*"}],
        }
    }


def test_solr_facets() -> None:
    fc = SolrFacets.of(
        FacetTerms(name=FieldName("types"), field=Fields.entity_type),
        FacetArbitraryRange(
            name=FieldName("stars"),
            field=FieldName("stars"),
            ranges=[FacetRange(start="*", to=100), FacetRange(start=100, to=200), FacetRange(start=200, to="*")],
        ),
    )
    assert fc.to_dict() == {
        "stars": {
            "type": "range",
            "field": "stars",
            "ranges": [{"from": "*", "to": 100}, {"from": 100, "to": 200}, {"from": 200, "to": "*"}],
        },
        "types": {
            "type": "terms",
            "field": "_type",
            "missing": False,
            "numBuckets": False,
            "allBuckets": False,
        },
    }


def test_facet_buckets() -> None:
    fb = FacetBuckets(
        buckets=[FacetCount(field=FieldName("electronic"), count=5), FacetCount(field=FieldName("garden"), count=10)]
    )
    assert fb.to_dict() == {"buckets": [{"val": "electronic", "count": 5}, {"val": "garden", "count": 10}]}

    fb_str = """{
      "buckets":[
         {"val":"electronics", "count":12},
         {"val":"currency", "count":4},
         {"val":"memory", "count":3}
      ]
    }"""
    assert FacetBuckets.model_validate_json(fb_str) == FacetBuckets(
        buckets=[
            FacetCount(field=FieldName("electronics"), count=12),
            FacetCount(field=FieldName("currency"), count=4),
            FacetCount(field=FieldName("memory"), count=3),
        ]
    )


def test_serialize_solr_query():
    q = SolrQuery.query_all_fields("name:hello")
    assert q.to_dict() == {"query": "name:hello", "fields": ["*", "score"], "sort": ""}

    q = SolrQuery.query_all_fields("name:hello").with_sort([(Fields.name, SortDirection.asc)])
    assert q.to_dict() == {"query": "name:hello", "fields": ["*", "score"], "sort": "name asc"}

    q = SolrQuery.query_all_fields("name:hello").with_sort(
        [(Fields.name, SortDirection.asc), (Fields.creation_date, SortDirection.desc)]
    )
    assert q.to_dict() == {"query": "name:hello", "fields": ["*", "score"], "sort": "name asc,creationDate desc"}

    q = (
        SolrQuery.query_all_fields("name:test help")
        .with_facet(FacetTerms(name=FieldName("type"), field=FieldName("_type")))
        .add_sub_query(FieldName("details"), SubQuery(query="test", filter="", limit=1))
        .with_sort([(Fields.name, SortDirection.asc)])
    )
    assert q.to_dict() == {
        "query": "name:test help",
        "fields": ["*", "score", "details:[subquery]"],
        "sort": "name asc",
        "params": {"details.q": "test", "details.limit": "1"},
        "facet": {
            "type": {"type": "terms", "field": "_type", "missing": False, "numBuckets": False, "allBuckets": False}
        },
    }


def test_solr_bucket_facet_response() -> None:
    respones_str = """{
      "count":32,
      "categories":{
        "buckets":[
           {"val":"electronics", "count":12},
           {"val":"currency", "count":4},
           {"val":"memory", "count":3}
        ]
      },
      "memories":{
        "buckets":[
           {"val":"bike", "count":2},
           {"val":"chair", "count":4},
           {"val":"memory", "count":6}
        ]
      }
    }"""
    fr = SolrBucketFacetResponse.model_validate_json(respones_str)
    expected = SolrBucketFacetResponse(
        count=32,
        buckets={
            FieldName("categories"): FacetBuckets(
                buckets=[
                    FacetCount(field=FieldName("electronics"), count=12),
                    FacetCount(field=FieldName("currency"), count=4),
                    FacetCount(field=FieldName("memory"), count=3),
                ]
            ),
            FieldName("memories"): FacetBuckets(
                buckets=[
                    FacetCount(field=FieldName("bike"), count=2),
                    FacetCount(field=FieldName("chair"), count=4),
                    FacetCount(field=FieldName("memory"), count=6),
                ]
            ),
        },
    )
    assert fr == expected
    assert expected.to_dict() == json.loads(respones_str)


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
        r1 = await client.upsert([g])  # type:ignore
        assert_upsert_result(r1)

        qr = await client.query(SolrQuery.query_all_fields("_type:Group"))
        assert qr.responseHeader.status == 0
        assert qr.response.num_found == 1
        assert len(qr.response.docs) == 1

        sg = Group.from_dict(qr.response.docs[0])
        assert sg.score is not None and sg.score > 0
        assert sg.reset_solr_fields() == g


@pytest.mark.asyncio
async def test_status_for_non_existing_core(solr_config):
    cfg = SolrClientConfig(base_url=solr_config.base_url, core="blahh-blah", user=solr_config.user)
    async with DefaultSolrAdminClient(cfg) as client:
        status = await client.core_status(None)
        assert status is None


@pytest.mark.asyncio
async def test_status_for_existing_core(solr_config):
    async with DefaultSolrAdminClient(solr_config) as client:
        status = await client.core_status(None)
        print(status)
        assert status is not None
        assert status["name"] == solr_config.core
        assert status["schema"] == "managed-schema.xml"
        assert "dataDir" in status
        assert "config" in status
        assert "index" in status
        assert "userData" in status["index"]


@pytest.mark.asyncio
async def test_create_new_core(solr_config_no_core):
    solr_config = solr_config_no_core
    async with DefaultSolrAdminClient(solr_config) as client:
        res = await client.create(None)
        assert res is None

    async with DefaultSolrAdminClient(solr_config) as client:
        res = await client.core_status(None)
        assert res is not None

    async with DefaultSolrClient(solr_config) as client:
        resp = await client.modify_schema(
            SchemaCommandList(
                [
                    AddCommand(FieldTypes.string),
                    AddCommand(Field.of(Fields.kind, FieldTypes.string)),
                ]
            )
        )
        assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_create_same_core_twice(solr_config):
    random_name = "".join(random.choices(string.ascii_lowercase + string.digits, k=9))
    async with DefaultSolrAdminClient(solr_config) as client:
        res = await client.create(random_name)
        assert res is None

        with pytest.raises(SolrClientCreateCoreException):
            await client.create(random_name)


@pytest.mark.asyncio
async def test_sub_query(solr_search):
    async with DefaultSolrClient(solr_search) as client:
        u1 = test_entity_documents.user_tadej_pogacar
        u2 = test_entity_documents.user_jan_ullrich
        p = test_entity_documents.project_ai_stuff
        r1 = await client.upsert([u1, u2, p])
        assert_upsert_result(r1)

        creator_details = FieldName("creatorDetails")

        query = SolrQuery.query_all_fields("_type:Project").add_sub_query(
            creator_details,
            SubQuery(query="{!terms f=id v=$row.createdBy}", filter="{!terms f=_kind v=fullentity}", limit=1),
        )

        r2 = await client.query(query)
        assert len(r2.response.docs) == 1
        details = r2.response.docs[0][creator_details]
        assert len(details["docs"]) == 1
        user_doc = details["docs"][0]
        user = User.model_validate(user_doc)
        assert user.path == u2.path
        assert user.id == u2.id


@pytest.mark.asyncio
async def test_run_facet_query(solr_search):
    async with DefaultSolrClient(solr_search) as client:
        u1 = test_entity_documents.user_tadej_pogacar
        u2 = test_entity_documents.user_jan_ullrich
        p = test_entity_documents.project_ai_stuff
        r1 = await client.upsert([u1, u2, p])
        assert_upsert_result(r1)

        query = SolrQuery.query_all_fields("_type:*").with_facet(
            FacetTerms(name=Fields.entity_type, field=Fields.entity_type)
        )

        r2 = await client.query(query)
        assert len(r2.response.docs) == 3
        assert r2.facets == SolrBucketFacetResponse(
            count=3,
            buckets={
                Fields.entity_type: FacetBuckets.of(
                    FacetCount(field=FieldName("User"), count=2), FacetCount(field=FieldName("Project"), count=1)
                )
            },
        )
