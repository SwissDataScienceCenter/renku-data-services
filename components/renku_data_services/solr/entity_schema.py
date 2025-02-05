"""Defines the solr schema used for the renku entities."""

from typing import Final

from renku_data_services.solr.solr_migrate import SchemaMigration
from renku_data_services.solr.solr_schema import (
    AddCommand,
    Analyzer,
    CopyFieldRule,
    Field,
    FieldName,
    FieldType,
    Filters,
    SchemaCommand,
    Tokenizers,
    TypeName,
)


class Fields:
    """A collection of fields."""

    created_by = FieldName("createdBy")
    creation_date = FieldName("creationDate")
    description = FieldName("description")
    entity_type = FieldName("_type")
    kind = FieldName("_kind")
    first_name = FieldName("firstName")
    id = FieldName("id")
    last_name = FieldName("lastName")
    members = FieldName("members")
    name = FieldName("name")
    repositories = FieldName("repositories")
    slug = FieldName("slug")
    visibility = FieldName("visibility")
    keywords = FieldName("keywords")
    namespace = FieldName("namespace")
    content_all = FieldName("content_all")
    # virtual score field
    score = FieldName("score")


class Analyzers:
    """A collection of analyzers."""

    text_index = Analyzer(
        tokenizer=Tokenizers.uax29UrlEmail,
        filters=[
            Filters.lowercase,
            Filters.stop,
            Filters.english_minimal_stem,
            Filters.ascii_folding,
            Filters.edgeNgram(2, 8, True),
        ],
    )

    text_query = Analyzer(
        tokenizer=Tokenizers.uax29UrlEmail,
        filters=[
            Filters.lowercase,
            Filters.stop,
            Filters.english_minimal_stem,
            Filters.ascii_folding,
        ],
    )


class FieldTypes:
    """A collection of field types."""

    id: FieldType = FieldType.id(TypeName("SearchId")).make_doc_value()
    string: FieldType = FieldType.str(TypeName("SearchString")).make_doc_value()
    text: FieldType = (
        FieldType.text(TypeName("SearchText"))
        .with_index_analyzer(Analyzers.text_index)
        .with_query_analyzer(Analyzers.text_query)
    )
    text_all: FieldType = (
        FieldType.text(TypeName("SearchTextAll"))
        .with_index_analyzer(Analyzers.text_index)
        .with_query_analyzer(Analyzers.text_query)
        .make_multi_valued()
    )
    date_time: FieldType = FieldType.date_time_point(TypeName("SearchDateTime"))


initial_entity_schema: Final[list[SchemaCommand]] = [
    AddCommand(FieldTypes.id),
    AddCommand(FieldTypes.string),
    AddCommand(FieldTypes.text),
    AddCommand(FieldTypes.date_time),
    AddCommand(Field.of(Fields.entity_type, FieldTypes.string)),
    AddCommand(Field.of(Fields.kind, FieldTypes.string)),
    AddCommand(Field.of(Fields.name, FieldTypes.text)),
    AddCommand(Field.of(Fields.slug, FieldTypes.string)),
    AddCommand(Field.of(Fields.repositories, FieldTypes.string).make_multi_valued()),
    AddCommand(Field.of(Fields.visibility, FieldTypes.string)),
    AddCommand(Field.of(Fields.description, FieldTypes.text)),
    AddCommand(Field.of(Fields.created_by, FieldTypes.id)),
    AddCommand(Field.of(Fields.creation_date, FieldTypes.date_time)),
    # text all
    AddCommand(FieldTypes.text_all),
    AddCommand(Field.of(Fields.content_all, FieldTypes.text_all).make_multi_valued()),
    AddCommand(CopyFieldRule(source=Fields.name, dest=Fields.content_all)),
    AddCommand(CopyFieldRule(source=Fields.description, dest=Fields.content_all)),
    AddCommand(CopyFieldRule(source=Fields.slug, dest=Fields.content_all)),
    AddCommand(CopyFieldRule(source=Fields.repositories, dest=Fields.content_all)),
    # user fields
    AddCommand(Field.of(Fields.first_name, FieldTypes.string)),
    AddCommand(Field.of(Fields.last_name, FieldTypes.string)),
    AddCommand(CopyFieldRule(source=Fields.first_name, dest=Fields.content_all)),
    AddCommand(CopyFieldRule(source=Fields.last_name, dest=Fields.content_all)),
    # keywords
    AddCommand(Field.of(Fields.keywords, FieldTypes.string).make_multi_valued()),
    AddCommand(CopyFieldRule(source=Fields.keywords, dest=Fields.content_all)),
    # namespace
    AddCommand(Field.of(Fields.namespace, FieldTypes.string)),
    AddCommand(CopyFieldRule(source=Fields.namespace, dest=Fields.content_all)),
]


all_migrations: Final[list[SchemaMigration]] = [
    SchemaMigration(version=9, commands=initial_entity_schema, requires_reindex=True)
]
