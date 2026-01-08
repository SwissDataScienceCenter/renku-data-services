"""Model for creating solr lucene queries."""

import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import NewType

from renku_data_services.authz.models import Visibility
from renku_data_services.base_models.nel import Nel
from renku_data_services.solr.entity_documents import EntityType
from renku_data_services.solr.entity_schema import Fields
from renku_data_services.solr.solr_schema import FieldName

SolrToken = NewType("SolrToken", str)

# Escapes query characters for solr. This is taken from here:
# https://github.com/apache/solr/blob/bcb9f144974ed07aa3b66766302474542067b522/solr/solrj/src/java/org/apache/solr/client/solrj/util/ClientUtils.java#L163
__defaultSpecialChars = '\\+-!():^[]"{}~*?|&;/'


def __escape(input: str, bad_chars: str) -> str:
    output = ""
    for c in input:
        if c.isspace() or bad_chars.find(c) >= 0:
            output += "\\"

        output += c

    return output


def __escape_query(input: str) -> str:
    return __escape(input, __defaultSpecialChars)


def empty() -> SolrToken:
    """Return the empty string."""
    return SolrToken("")


def all_query() -> SolrToken:
    """A solr query to return all documents."""
    return SolrToken("*:*")


def from_str(input: str) -> SolrToken:
    """Create a solr query part from a string."""
    return SolrToken(__escape_query(input))


def prefix_search(input: str) -> SolrToken:
    """Create a solr query part matching input prefixes."""
    return SolrToken(f"{__escape_query(input)}*")


def from_visibility(v: Visibility) -> SolrToken:
    """Create a solr query value for a visibility."""
    return SolrToken(v.value.lower())


def from_entity_type(et: EntityType) -> SolrToken:
    """Create a solr query value for an entity type."""
    return SolrToken(et.value)


def from_datetime(dt: datetime) -> SolrToken:
    """Convert the datetime into a solr query value.

    Solr uses UTC formatted timestamps, preferring the `Z` suffix
    indicating UTC timezone.

    https://solr.apache.org/guide/solr/latest/indexing-guide/date-formatting-math.html
    """
    dt = dt.astimezone(UTC).replace(microsecond=0)
    dt_str = dt.isoformat()
    dt_str = dt_str.replace("+00:00", "Z")  # couldn't find a good way…
    return SolrToken(__escape(dt_str, ":"))


def from_date_range(min: datetime, max: datetime) -> SolrToken:
    """Convert a date range into a solr query value."""
    start = from_datetime(min)
    end = from_datetime(max)
    return SolrToken(f"[{start} TO {end}]")


def field_is(field: FieldName, value: SolrToken) -> SolrToken:
    """Create a solr query part for a field."""
    return SolrToken(f"{field}:{value}")


def field_exists(field: FieldName) -> SolrToken:
    """Look for an existing field."""
    return field_is(field, SolrToken("[* TO *]"))


def field_not_exists(field: FieldName) -> SolrToken:
    """Return a query part checking if a field does not exist."""
    return SolrToken(f"-{field}:[* TO *]")


def field_is_any(field: FieldName, value: Nel[SolrToken]) -> SolrToken:
    """Search for any value in the given field."""
    if value.more_values == []:
        return field_is(field, value.value)
    else:
        vs = fold_or(value)
        return field_is(field, SolrToken(f"({vs})"))


def namespace_path_is_any(value: Nel[str]) -> SolrToken:
    """Search for entities in the given namespaces or below."""
    path_or_below = [x for k in [[from_str(e), prefix_search(f"{e}/")] for e in value] for x in k]
    vs = fold_or(path_or_below)
    return field_is(Fields.namespace_path, SolrToken(f"({vs})"))


def type_is(et: EntityType) -> SolrToken:
    """Search for the type field."""
    return field_is(Fields.entity_type, from_entity_type(et))


def fold_and(tokens: Iterable[SolrToken]) -> SolrToken:
    """Combine multiple solr query parts with AND."""
    return SolrToken(" AND ".join(tokens))


def fold_or(tokens: Iterable[SolrToken]) -> SolrToken:
    """Combine multiple solr query parts with OR."""
    return SolrToken(" OR ".join(tokens))


def id_is(id: str) -> SolrToken:
    """Create a solr query part for a given id."""
    return field_is(Fields.id, from_str(id))


def id_in(ids: Nel[str]) -> SolrToken:
    """Create a solr query part that matches any given id."""
    return field_is_any(Fields.id, ids.map(from_str))


def id_not_exists() -> SolrToken:
    """Create a solr query part matching documents without an id."""
    return field_not_exists(Fields.id)


def public_or_ids(allowed_ids: list[str]) -> SolrToken:
    """Create a solr query part selecting public entities or ones with the given ids."""
    id_nel: Nel[str] | None = Nel.from_list(allowed_ids)
    match id_nel:
        case Nel() as nl:
            return SolrToken(f"({public_only()} OR {id_in(nl)})")
        case _:
            return public_only()


def created_is(dt: datetime) -> SolrToken:
    """Create a solr query part comparing the creation_date."""
    return field_is(Fields.creation_date, from_datetime(dt))


def created_range(min: datetime, max: datetime) -> SolrToken:
    """Create a solr query part comparing the creation_date."""
    return field_is(Fields.creation_date, from_date_range(min, max))


def created_gt(dt: datetime) -> SolrToken:
    """Create a solr query part comparing the creation_date."""
    return field_is(Fields.creation_date, SolrToken(f"[{from_datetime(dt)} TO *]"))


def created_lt(dt: datetime) -> SolrToken:
    """Create a solr query part comparing the creation_date."""
    return field_is(Fields.creation_date, SolrToken(f"[* TO {from_datetime(dt)}]"))


def all_entities() -> SolrToken:
    """Searches renku entity documents."""
    return field_is(Fields.kind, SolrToken("fullentity"))


def public_only() -> SolrToken:
    """Search only public entities."""
    return field_is(Fields.visibility, from_visibility(Visibility.PUBLIC))


def content_all(text: str) -> SolrToken:
    """Search the content_all field with fuzzy searching each term."""
    terms: list[SolrToken] = list(map(lambda s: SolrToken(__escape_query(s)), re.split("\\s+", text)))
    terms_str = "(" + " ".join(terms) + ")"
    return SolrToken(f"{Fields.content_all}:{terms_str}")


def created_by_exists() -> SolrToken:
    """Query part that requires an existing createdBy field for a project document."""
    return SolrToken("(createdBy:[* TO *] OR (*:* AND -_type:Project))")
