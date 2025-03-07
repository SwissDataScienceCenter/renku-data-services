"""Parser for the user query ast."""

import enum
from parsy import Parser, char_from, from_enum, regex, string, any_char, seq, test_char
from renku_data_services.search.user_query import Comparison, Field, Nel, Order, OrderBy, SortableField, TypeIs
from renku_data_services.solr.entity_documents import EntityType
from renku_data_services.solr.solr_client import SortDirection


def valid_char(c: str) -> bool:
    return ord(c) > 32 and c != '"' and c != "\\" and c != ","


class ParsePrimitives:
    whitespace: Parser = regex(r"\s*")
    comma: Parser = string(",") << whitespace

    char_basic: Parser = test_char(func=valid_char, description="simple string")
    char_esc: Parser = string("\\") >> (string('"') | string("\\"))
    no_quote: Parser = test_char(lambda c: c != '"', description="no quote")

    string_basic: Parser = char_basic.many().concat()
    string_quoted: Parser = string('"') >> (char_esc | no_quote).many().concat() << string('"')
    string_value: Parser = string_quoted | string_basic

    string_values: Parser = string_value.sep_by(comma, min=1).map(Nel.unsafe_from_list)

    sortable_field: Parser = from_enum(SortableField, lambda s: s.lower())
    sort_direction: Parser = from_enum(SortDirection, lambda s: s.lower())
    entity_type: Parser = from_enum(EntityType, lambda s: s.lower())

    is_equal: Parser = string(Comparison.is_equal.value).result(Comparison.is_equal)
    is_gt: Parser = string(Comparison.is_greater_than).result(Comparison.is_greater_than)
    is_lt: Parser = string(Comparison.is_lower_than).result(Comparison.is_lower_than)

    ordered_by: Parser = seq((sortable_field << string("-")), sort_direction).combine(OrderBy)

    ordered_by_nel: Parser = ordered_by.sep_by(comma, min=1).map(Nel.unsafe_from_list)
    entity_type_nel: Parser = entity_type.sep_by(comma, min=1).map(Nel.unsafe_from_list)

    sort_term: Parser = string("sort") >> is_equal >> ordered_by_nel.map(Order)

    type_is: Parser = string(Field.type.value) >> is_equal >> entity_type_nel.map(TypeIs)

    term_is: Parser = seq(from_enum(Field) >> is_equal, string_values)
