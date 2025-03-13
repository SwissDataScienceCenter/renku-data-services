"""Tests for the solr_user_query module."""

from renku_data_services.search.solr_user_query import LuceneQueryInterpreter as L
from renku_data_services.search.user_query import OrderBy, SortableField
from renku_data_services.solr.entity_schema import Fields
from renku_data_services.solr.solr_client import SortDirection


def test_to_solr_sort() -> None:
    assert L._to_solr_sort(OrderBy(field=SortableField.fname, direction=SortDirection.asc)) == (
        Fields.name,
        SortDirection.asc,
    )
