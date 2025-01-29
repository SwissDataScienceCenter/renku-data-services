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
    created_by: FieldName = FieldName("createdBy")
    creation_date: FieldName = FieldName("creationDate")
    description: FieldName = FieldName("description")
    entityType: FieldName = FieldName("_type")
    kind: FieldName = FieldName("_kind")
    firstName: FieldName = FieldName("firstName")
    id: FieldName = FieldName("id")
    lastName: FieldName = FieldName("lastName")
    members: FieldName = FieldName("members")
    name: FieldName = FieldName("name")
    repositories: FieldName = FieldName("repositories")
    slug: FieldName = FieldName("slug")
    visibility: FieldName = FieldName("visibility")
    keywords: FieldName = FieldName("keywords")
    namespace: FieldName = FieldName("namespace")
    contentAll: FieldName = FieldName("content_all")
    # virtual score field
    score: FieldName = FieldName("score")


class Analyzers:
    textIndex = Analyzer(
        tokenizer=Tokenizers.uax29UrlEmail,
        filters=[
            Filters.lowercase,
            Filters.stop,
            Filters.english_minimal_stem,
            Filters.ascii_folding,
            Filters.edgeNgram(2, 8, True),
        ],
    )

    textQuery = Analyzer(
        tokenizer=Tokenizers.uax29UrlEmail,
        filters=[
            Filters.lowercase,
            Filters.stop,
            Filters.english_minimal_stem,
            Filters.ascii_folding,
        ],
    )


class FieldTypes:
    id: FieldType = FieldType.id(TypeName("SearchId")).make_doc_value()
    string: FieldType = FieldType.str(TypeName("SearchString")).make_doc_value()
    text: FieldType = (
        FieldType.text(TypeName("SearchText"))
        .with_index_analyzer(Analyzers.textIndex)
        .with_query_analyzer(Analyzers.textQuery)
    )
    textAll: FieldType = (
        FieldType.text(TypeName("SearchTextAll"))
        .with_index_analyzer(Analyzers.textIndex)
        .with_query_analyzer(Analyzers.textQuery)
        .make_multi_valued()
    )
    dateTime: FieldType = FieldType.dateTimePoint(TypeName("SearchDateTime"))


initial_entity_schema: list[SchemaCommand] = [
    AddCommand(FieldTypes.id),
    AddCommand(FieldTypes.string),
    AddCommand(FieldTypes.text),
    AddCommand(FieldTypes.dateTime),
    AddCommand(Field.of(Fields.entityType, FieldTypes.string)),
    AddCommand(Field.of(Fields.kind, FieldTypes.string)),
    AddCommand(Field.of(Fields.name, FieldTypes.text)),
    AddCommand(Field.of(Fields.slug, FieldTypes.string)),
    AddCommand(Field.of(Fields.repositories, FieldTypes.string).make_multi_valued()),
    AddCommand(Field.of(Fields.visibility, FieldTypes.string)),
    AddCommand(Field.of(Fields.description, FieldTypes.text)),
    AddCommand(Field.of(Fields.created_by, FieldTypes.id)),
    AddCommand(Field.of(Fields.creation_date, FieldTypes.dateTime)),
    # text all
    AddCommand(FieldTypes.textAll),
    AddCommand(Field.of(Fields.contentAll, FieldTypes.textAll).make_multi_valued()),
    AddCommand(CopyFieldRule(source=Fields.name, dest=Fields.contentAll)),
    AddCommand(CopyFieldRule(source=Fields.description, dest=Fields.contentAll)),
    AddCommand(CopyFieldRule(source=Fields.slug, dest=Fields.contentAll)),
    AddCommand(CopyFieldRule(source=Fields.repositories, dest=Fields.contentAll)),
    # user fields
    AddCommand(Field.of(Fields.firstName, FieldTypes.string)),
    AddCommand(Field.of(Fields.lastName, FieldTypes.string)),
    AddCommand(CopyFieldRule(source=Fields.firstName, dest=Fields.contentAll)),
    AddCommand(CopyFieldRule(source=Fields.lastName, dest=Fields.contentAll)),
    # keywords
    AddCommand(Field.of(Fields.keywords, FieldTypes.string).make_multi_valued()),
    AddCommand(CopyFieldRule(source=Fields.keywords, dest=Fields.contentAll)),
    # namespace
    AddCommand(Field.of(Fields.namespace, FieldTypes.string)),
    AddCommand(CopyFieldRule(source=Fields.namespace, dest=Fields.contentAll)),
]


all_migrations: list[SchemaMigration] = [
    SchemaMigration(version=9, commands=initial_entity_schema, requires_reindex=True)
]
