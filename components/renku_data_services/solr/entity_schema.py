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
    ReplaceCommand,
    SchemaCommand,
    Tokenizers,
    TypeName,
)


class Fields:
    """A collection of fields."""

    created_by: Final[FieldName] = FieldName("createdBy")
    creation_date: Final[FieldName] = FieldName("creationDate")
    description: Final[FieldName] = FieldName("description")
    entity_type: Final[FieldName] = FieldName("_type")
    kind: Final[FieldName] = FieldName("_kind")
    first_name: Final[FieldName] = FieldName("firstName")
    id: Final[FieldName] = FieldName("id")
    last_name: Final[FieldName] = FieldName("lastName")
    members: Final[FieldName] = FieldName("members")
    name: Final[FieldName] = FieldName("name")
    name_keyword: Final[FieldName] = FieldName("nameKeyword")
    repositories: Final[FieldName] = FieldName("repositories")
    slug: Final[FieldName] = FieldName("slug")
    visibility: Final[FieldName] = FieldName("visibility")
    keywords: Final[FieldName] = FieldName("keywords")
    namespace: Final[FieldName] = FieldName("namespace")
    content_all: Final[FieldName] = FieldName("content_all")
    deleted: Final[FieldName] = FieldName("deleted")
    readonly: Final[FieldName] = FieldName("readonly")
    storageType: Final[FieldName] = FieldName("storageType")
    path: Final[FieldName] = FieldName("path")
    namespace_path: Final[FieldName] = FieldName("namespacePath")
    is_namespace: Final[FieldName] = FieldName("isNamespace")

    # virtual score field
    score: Final[FieldName] = FieldName("score")

    # sub query fields
    creator_details: Final[FieldName] = FieldName("creatorDetails")
    namespace_details: Final[FieldName] = FieldName("namespaceDetails")

    # data connector fields
    doi: Final[FieldName] = FieldName("doi")
    publisher_name: Final[FieldName] = FieldName("publisherName")


class Analyzers:
    """A collection of analyzers."""

    text_index: Final[Analyzer] = Analyzer(
        tokenizer=Tokenizers.uax29UrlEmail,
        filters=[
            Filters.lowercase,
            Filters.stop,
            Filters.english_minimal_stem,
            Filters.ascii_folding,
            Filters.edgeNgram(2, 8, True),
        ],
    )

    text_query: Final[Analyzer] = Analyzer(
        tokenizer=Tokenizers.uax29UrlEmail,
        filters=[
            Filters.lowercase,
            Filters.stop,
            Filters.english_minimal_stem,
            Filters.ascii_folding,
        ],
    )

    keyword_case_insensitive: Final[Analyzer] = Analyzer(
        tokenizer=Tokenizers.keyword,
        filters=[Filters.lowercase],
    )

    # Analyzers for the `name` field only. Unlike `text_index`, these use the
    # whitespace tokenizer so hyphenated values stay intact long enough for the
    # wordDelimiterGraph filter to split them. That filter then emits the word
    # parts ("test", "project"), the catenated form ("testproject") and -- via
    # preserveOriginal -- the whole token ("test-project"), so the name field
    # matches all of those (including the hyphenated whole, which the fuzzy query
    # operator can only hit because preserveOriginal keeps it in the index).
    name_index: Final[Analyzer] = Analyzer(
        tokenizer=Tokenizers.whitespace,
        filters=[
            Filters.word_delimiter_graph(catenate=True, preserve_original=True),
            Filters.flatten_graph,
            Filters.lowercase,
            Filters.stop,
            Filters.english_minimal_stem,
            Filters.ascii_folding,
            Filters.edgeNgram(2, 8, True),
        ],
    )

    name_query: Final[Analyzer] = Analyzer(
        tokenizer=Tokenizers.whitespace,
        filters=[
            # No catenate or flattenGraph at query time; the parser handles the graph.
            Filters.word_delimiter_graph(catenate=False, preserve_original=True),
            Filters.lowercase,
            Filters.stop,
            Filters.english_minimal_stem,
            Filters.ascii_folding,
        ],
    )


class FieldTypes:
    """A collection of field types."""

    id: Final[FieldType] = FieldType.id(TypeName("SearchId")).make_doc_value()
    string: Final[FieldType] = FieldType.str(TypeName("SearchString")).make_doc_value()
    boolean: Final[FieldType] = FieldType.boolean(TypeName("SearchBool"))
    text: Final[FieldType] = (
        FieldType.text(TypeName("SearchText"))
        .with_index_analyzer(Analyzers.text_index)
        .with_query_analyzer(Analyzers.text_query)
    )
    text_name: Final[FieldType] = (
        FieldType.text(TypeName("SearchTextName"))
        .with_index_analyzer(Analyzers.name_index)
        .with_query_analyzer(Analyzers.name_query)
    )
    """Like `text`, but splits hyphenated/camelCase tokens into parts while also
    keeping the whole and catenated forms. Used only for the `name` field."""

    text_all: Final[FieldType] = (
        FieldType.text(TypeName("SearchTextAll"))
        .with_index_analyzer(Analyzers.text_index)
        .with_query_analyzer(Analyzers.text_query)
        .make_multi_valued()
    )
    date_time: Final[FieldType] = FieldType.date_time_point(TypeName("SearchDateTime"))

    keyword: Final[FieldType] = (
        FieldType.text(TypeName("Keyword")).make_stored().with_analyzer(Analyzers.keyword_case_insensitive)
    )
    """keyword is a field type that is not changed at all by the tokenizer, and is stored unchanged
    but is searched in case-insensitive manner. Note, analyzers cannot be added to StrField, so we use TextField."""


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
    AddCommand(FieldTypes.text_all),
    # text all
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
    SchemaMigration(version=9, commands=initial_entity_schema, requires_reindex=True),
    SchemaMigration(
        version=10,
        commands=[AddCommand(FieldTypes.boolean), AddCommand(Field.of(Fields.deleted, FieldTypes.boolean))],
        requires_reindex=False,
    ),
    SchemaMigration(
        version=11,
        commands=[
            AddCommand(Field.of(Fields.readonly, FieldTypes.boolean)),
            AddCommand(Field.of(Fields.storageType, FieldTypes.string)),
        ],
        requires_reindex=False,
    ),
    SchemaMigration(
        version=12,
        commands=[
            AddCommand(Field.of(Fields.path, FieldTypes.id)),
            AddCommand(Field.of(Fields.namespace_path, FieldTypes.id)),
            AddCommand(Field.of(Fields.is_namespace, FieldTypes.boolean)),
        ],
        requires_reindex=True,
    ),
    SchemaMigration(
        version=13,
        commands=[
            AddCommand(FieldTypes.keyword),
            AddCommand(Field.of(Fields.doi, FieldTypes.keyword)),
            AddCommand(CopyFieldRule(source=Fields.doi, dest=Fields.content_all)),
            AddCommand(Field.of(Fields.publisher_name, FieldTypes.keyword)),
            AddCommand(CopyFieldRule(source=Fields.publisher_name, dest=Fields.content_all)),
        ],
        requires_reindex=False,
    ),
    SchemaMigration(
        version=14,
        commands=[
            ReplaceCommand(Field.of(Fields.keywords, FieldTypes.keyword).make_multi_valued()),
        ],
        requires_reindex=True,
    ),
    SchemaMigration(
        version=15,
        commands=[
            AddCommand(FieldTypes.text_name),
            ReplaceCommand(Field.of(Fields.name, FieldTypes.text_name)),
            # An untokenized, case-insensitive copy of the name (FieldTypes.keyword
            # keeps the whole value including spaces as a single token) so an exact
            # title can be matched/boosted regardless of spaces or other separators.
            AddCommand(Field.of(Fields.name_keyword, FieldTypes.keyword)),
            AddCommand(CopyFieldRule(source=Fields.name, dest=Fields.name_keyword)),
        ],
        requires_reindex=True,
    ),
]
