"""Tests for solr_token."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import renku_data_services.search.solr_token as st
from renku_data_services.authz.models import Visibility
from renku_data_services.base_models.nel import Nel
from renku_data_services.solr.entity_documents import EntityType
from renku_data_services.solr.solr_schema import FieldName

ref_date: datetime = datetime(2024, 2, 27, 15, 34, 55, tzinfo=UTC)
ref_date2: datetime = datetime(2024, 4, 26, 7, 16, 12, tzinfo=ZoneInfo("Europe/Berlin"))


def test_empty() -> None:
    assert st.empty() == ""


def test_all_query() -> None:
    assert st.all_query() == "*:*"


def test_from_str() -> None:
    assert st.from_str("abc") == "abc"
    assert st.from_str("a b c") == "a\\ b\\ c"
    assert st.from_str("a(b)c") == "a\\(b\\)c"
    assert st.from_str("a+b+c") == "a\\+b\\+c"
    assert st.from_str("test!") == "test\\!"
    assert st.from_str("a\tb") == "a\\\tb"


def test_from_visibility() -> None:
    assert st.from_visibility(Visibility.PRIVATE) == "private"
    assert st.from_visibility(Visibility.PUBLIC) == "public"


def test_from_entity_typen() -> None:
    assert st.from_entity_type(EntityType.project) == "Project"
    assert st.from_entity_type(EntityType.group) == "Group"
    assert st.from_entity_type(EntityType.user) == "User"


def test_from_datetime() -> None:
    assert st.from_datetime(ref_date) == "2024-02-27T15\\:34\\:55Z"
    assert st.from_datetime(ref_date2) == "2024-04-26T05\\:16\\:12Z"


def test_field_is() -> None:
    assert st.field_is(FieldName("name"), st.from_str("Tadej")) == "name:Tadej"


def test_field_exists() -> None:
    assert st.field_exists(FieldName("_type")) == "_type:[* TO *]"


def test_field_not_exists() -> None:
    assert st.field_not_exists(FieldName("_type")) == "-_type:[* TO *]"


def test_field_is_any() -> None:
    v = Nel.of(st.from_visibility(Visibility.PUBLIC), st.from_visibility(Visibility.PRIVATE))
    assert st.field_is_any(FieldName("visibility"), v) == "visibility:(public OR private)"

    v = Nel.of(st.from_str("hello"))
    assert st.field_is_any(FieldName("name"), v) == "name:hello"


def test_id_is() -> None:
    assert st.id_is("id12") == "id:id12"
    assert st.id_is("id:121") == "id:id\\:121"


def test_id_in() -> None:
    assert st.id_in(Nel.of("1", "2", "thre e")) == "id:(1 OR 2 OR thre\\ e)"


def test_id_not_exists() -> None:
    assert st.id_not_exists() == "-id:[* TO *]"


def test_public_or_ids() -> None:
    assert st.public_or_ids(["one", "id2"]) == "(visibility:public OR id:(one OR id2))"
    assert st.public_or_ids(["id1"]) == "(visibility:public OR id:id1)"


def test_public_only() -> None:
    assert st.public_only() == "visibility:public"


def test_all_entities() -> None:
    assert st.all_entities() == "_kind:fullentity"


def test_created_is() -> None:
    assert st.created_is(ref_date) == "creationDate:2024-02-27T15\\:34\\:55Z"


def test_created_range() -> None:
    assert (
        st.created_range(ref_date, ref_date + timedelta(days=2))
        == "creationDate:[2024-02-27T15\\:34\\:55Z TO 2024-02-29T15\\:34\\:55Z]"
    )


def test_created_gt() -> None:
    assert st.created_gt(ref_date) == "creationDate:[2024-02-27T15\\:34\\:55Z TO *]"


def test_created_lt() -> None:
    assert st.created_lt(ref_date) == "creationDate:[* TO 2024-02-27T15\\:34\\:55Z]"


def test_fold_and() -> None:
    assert (
        st.fold_and([st.public_only(), st.all_entities(), st.id_is("1234")])
        == "visibility:public AND _kind:fullentity AND id:1234"
    )


def test_fold_or() -> None:
    assert (
        st.fold_or([st.public_only(), st.all_entities(), st.id_is("1234")])
        == "visibility:public OR _kind:fullentity OR id:1234"
    )


def test_created_by_exists() -> None:
    assert st.created_by_exists() == "(createdBy:[* TO *] OR (*:* AND -_type:Project))"


def test_content_all() -> None:
    assert st.content_all("abc") == "content_all:(abc)"
    assert st.content_all("a+b+c") == "content_all:(a\\+b\\+c)"
    assert st.content_all("ab cd") == "content_all:(ab\\ cd)"
    assert st.content_all("ab    cd") == "content_all:(ab\\ \\ \\ \\ cd)"
