from renku_data_services.solr.solr_schema import (
    SchemaCommand,
    Tokenizers,
    TypeName,
    Filters,
    SchemaCommandList,
    Analyzer,
    FieldTypeClasses,
    AddCommand,
    FieldType,
    Field,
    FieldName,
    CopyFieldRule,
)


def test_multiple_commands_in_one_object():
    tokenizer = Tokenizers.classic
    analyzer = Analyzer(tokenizer=tokenizer, filters=[Filters.ngram])

    ft = FieldType(name=TypeName("name_s"), clazz=FieldTypeClasses.type_text, index_analyzer=analyzer)

    cmds: list[SchemaCommand] = [
        AddCommand(Field.of(name=FieldName("project_name_s"), type=ft)),
        AddCommand(Field.of(name=FieldName("user_name_s"), type=ft)),
        AddCommand(CopyFieldRule(source=FieldName("username"), dest=FieldName("content_all"))),
    ]

    json = SchemaCommandList(value=cmds).to_json()
    assert (
        json
        == '{"add-field":{"name": "project_name_s", "type": "name_s"},"add-field":{"name": "user_name_s", "type": "name_s"},"add-copy-field":{"source": "username", "dest": "content_all"}}'
    )

def test_encode_schema_command_add():
    v = AddCommand(Field(name=FieldName("description"), type=TypeName("integer")))
    assert (SchemaCommandList([v]).to_json(), """{"add-field":{"name":"description","type":"integer"}}""")


def test_encode_filter_with_settings():
    filter = Filters.edgeNgram()
    json = filter.to_dict()
    assert json == {"minGramSize": "3", "maxGramSize": "6", "preserveOriginal": "true", "name": "edgeNGram"}


def test_encode_filter_without_settings():
    filter = Filters.english_minimal_stem
    json = filter.to_dict()
    assert json == {"name": "englishMinimalStem"}
