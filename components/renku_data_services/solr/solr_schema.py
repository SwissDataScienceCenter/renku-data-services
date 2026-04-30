"""Schema modification for solr."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, NewType, Self, final

import pydantic
from pydantic import AliasChoices, BaseModel, model_serializer

TypeName = NewType("TypeName", str)
FieldName = NewType("FieldName", str)


class SchemaModel(BaseModel, frozen=True):
    """Base class of a solr schema type."""

    def to_dict(self) -> dict[str, Any]:
        """Return the dict representation of this schema model type."""
        return self.model_dump(by_alias=True, exclude_defaults=True)

    def to_json(self) -> str:
        """Return this schema model as JSON."""
        return json.dumps(self.to_dict())


@final
class Tokenizer(SchemaModel, frozen=True):
    """A solr tokenizer: https://solr.apache.org/guide/solr/latest/indexing-guide/tokenizers.html."""

    name: str


@final
class Tokenizers:
    """Some predefined tokenizer."""

    standard: Tokenizer = Tokenizer(name="standard")
    whitespace: Tokenizer = Tokenizer(name="whitespace")
    classic: Tokenizer = Tokenizer(name="classic")

    # https://solr.apache.org/guide/solr/latest/indexing-guide/tokenizers.html#uax29-url-email-tokenizer
    uax29UrlEmail: Tokenizer = Tokenizer(name="uax29UrlEmail")
    icu: Tokenizer = Tokenizer(name="icu")
    openNlp: Tokenizer = Tokenizer(name="openNlp")

    # The keyword tokenizer treats the entire field as a single token
    # See https://solr.apache.org/guide/solr/latest/indexing-guide/tokenizers.html#keyword-tokenizer
    keyword: Tokenizer = Tokenizer(name="keyword")


@final
class Filter(BaseModel):
    """Defines a SOLR filter. See https://solr.apache.org/guide/solr/latest/indexing-guide/filters.html."""

    name: str
    settings: dict | None = None

    @model_serializer()
    def to_dict(self) -> dict[str, Any]:
        """Return a dict representation for this filter."""
        match self.settings:
            case None:
                return {"name": self.name}
            case _:
                data = self.settings.copy()
                data.update({"name": self.name})
                return data


@final
class Filters:
    """A list of predefined filters supported by SOLR."""

    ascii_folding = Filter(name="asciiFolding")
    lowercase = Filter(name="lowercase")
    stop = Filter(name="stop")
    english_minimal_stem = Filter(name="englishMinimalStem")
    classic = Filter(name="classic")
    ngram = Filter(name="nGram")
    flattenGraph = Filter(name="flattenGraph")
    word = Filter(
        name="wordDelimiterGraph",
        settings={
            "splitOnCaseChange": "1",
            "catenateNumbers": "1",
            "catenateAll": "1",
            "preserveOriginal": "1",
            "splitOnNumerics": "0",
        },
    )

    @classmethod
    def edgeNgram(cls, min_gram_size: int = 3, maxGramSize: int = 6, preserve_original: bool = True) -> Filter:
        """Create a edgeNGram filter with the given settings."""
        return Filter(
            name="edgeNGram",
            settings={
                "minGramSize": f"{min_gram_size}",
                "maxGramSize": f"{maxGramSize}",
                "preserveOriginal": f"{json.dumps(preserve_original)}",
            },
        )


@final
class Analyzer(SchemaModel, frozen=True):
    """A solr analyzer: https://solr.apache.org/guide/solr/latest/indexing-guide/analyzers.html."""

    tokenizer: Tokenizer
    filters: list[Filter] = pydantic.Field(default_factory=list)


FieldTypeClass = NewType("FieldTypeClass", str)


@final
class FieldTypeClasses:
    """A list of field type classses."""

    type_int = FieldTypeClass("IntPointField")
    type_long = FieldTypeClass("LongPointField")
    type_float = FieldTypeClass("FloatPointField")
    type_double = FieldTypeClass("DoublePointField")
    type_text = FieldTypeClass("TextField")
    """TextField gets tokenized in Solr by default in our deployment."""
    type_str = FieldTypeClass("StrField")
    """StrField does not get tokenized in Solr by default in our deployment."""
    type_uuid = FieldTypeClass("UUIDField")
    type_rank = FieldTypeClass("RankField")
    type_date_point = FieldTypeClass("DatePointField")
    type_date_range = FieldTypeClass("DateRangeField")
    type_bool = FieldTypeClass("BoolField")


@final
class FieldType(SchemaModel, frozen=True):
    """A solr field type: https://solr.apache.org/guide/solr/latest/indexing-guide/field-type-definitions-and-properties.html."""

    name: TypeName
    clazz: FieldTypeClass = pydantic.Field(validation_alias=AliasChoices("clazz", "class"), serialization_alias="class")
    indexAnalyzer: Analyzer | None = None
    queryAnalyzer: Analyzer | None = None
    required: bool = False
    indexed: bool = False
    stored: bool = True
    multiValued: bool = False
    uninvertible: bool = False
    docValues: bool = False
    sortMissingLast: bool = True

    def make_doc_value(self) -> Self:
        """Return a copy with docValues=True."""
        return self.model_copy(update={"docValues": True})

    def make_multi_valued(self) -> Self:
        """Return a copy with multiValued=True."""
        return self.model_copy(update={"multiValued": True})

    def with_analyzer(self, a: Analyzer) -> Self:
        """Return a copy with both analyzers set to the given one."""
        return self.model_copy(update={"queryAnalyzer": a, "indexAnalyzer": a})

    def with_query_analyzer(self, a: Analyzer) -> Self:
        """Return a copy with query analyzers set to the given one."""
        return self.model_copy(update={"queryAnalyzer": a})

    def with_index_analyzer(self, a: Analyzer) -> Self:
        """Return a copy with index analyzers set to the given one."""
        return self.model_copy(update={"indexAnalyzer": a})

    def make_stored(self) -> Self:
        """Make the field "stored" so that original value of the field is stored and can be retrieved."""
        return self.model_copy(update={"stored": True})

    @classmethod
    def id(cls, name: TypeName) -> FieldType:
        """Create a field that can be used as a document id."""
        return FieldType(name=name, clazz=FieldTypeClasses.type_str)

    @classmethod
    def text(cls, name: TypeName) -> FieldType:
        """Create a text field type."""
        return FieldType(name=name, clazz=FieldTypeClasses.type_text)

    @classmethod
    def str(cls, name: TypeName) -> FieldType:
        """Create a StrField field type."""
        return FieldType(name=name, clazz=FieldTypeClasses.type_str)

    @classmethod
    def int(cls, name: TypeName) -> FieldType:
        """Create an IntPointField field type."""
        return FieldType(name=name, clazz=FieldTypeClasses.type_int)

    @classmethod
    def long(cls, name: TypeName) -> FieldType:
        """Create a LongPointField field type."""
        return FieldType(name=name, clazz=FieldTypeClasses.type_long)

    @classmethod
    def boolean(cls, name: TypeName) -> FieldType:
        """Create a boolean field type."""
        return FieldType(name=name, clazz=FieldTypeClasses.type_bool)

    @classmethod
    def double(cls, name: TypeName) -> FieldType:
        """Create a DoublePointField field type."""
        return FieldType(name=name, clazz=FieldTypeClasses.type_double)

    @classmethod
    def date_time(cls, name: TypeName) -> FieldType:
        """Create a DateRange field type."""
        return FieldType(name=name, clazz=FieldTypeClasses.type_date_range)

    @classmethod
    def date_time_point(cls, name: TypeName) -> FieldType:
        """Create a DatePoint field type."""
        return FieldType(name=name, clazz=FieldTypeClasses.type_date_point)


@final
class Field(SchemaModel, frozen=True):
    """A solr field: https://solr.apache.org/guide/solr/latest/indexing-guide/fields.html."""

    name: FieldName
    type: TypeName
    required: bool = False
    indexed: bool = True
    stored: bool = True
    multiValued: bool = False
    uninvertible: bool = False
    docValues: bool = True

    @classmethod
    def of(cls, name: FieldName, type: FieldType) -> Field:
        """Alternative constructor given a `FieldType` instead of a `TypeName`."""
        return Field(name=name, type=type.name)

    def make_multi_valued(self) -> Self:
        """Return a copy with multiValued=True."""
        return self.model_copy(update={"multiValued": True})


@final
class DynamicFieldRule(SchemaModel, frozen=True):
    """A solr dynamic field: https://solr.apache.org/guide/solr/latest/indexing-guide/dynamic-fields.html."""

    name: FieldName
    type: TypeName
    required: bool = False
    indexed: bool = True
    stored: bool = True
    multiValued: bool = False
    uninvertible: bool = False
    docValues: bool = True


@final
class CopyFieldRule(SchemaModel, frozen=True):
    """A solr copy field: https://solr.apache.org/guide/solr/latest/indexing-guide/copy-fields.html."""

    source: FieldName
    dest: FieldName
    maxChars: int | None = None


class SchemaCommand(ABC):
    """A base class for a schema command.

    A schema command is a single action modifying the solr schema.
    See https://solr.apache.org/guide/solr/latest/indexing-guide/schema-api.html
    """

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Return the dict representation for this schema command."""
        ...

    @abstractmethod
    def command_name(self) -> str:
        """Return the command name."""
        ...


@dataclass
@final
class AddCommand(SchemaCommand):
    """SchemaCommand to add a field, field-type, dynamic field or copy field."""

    value: Field | FieldType | DynamicFieldRule | CopyFieldRule

    def command_name(self) -> str:
        """Return the command name."""
        match self.value:
            case Field():
                return "add-field"

            case FieldType():
                return "add-field-type"

            case DynamicFieldRule():
                return "add-dynamic-field"

            case CopyFieldRule():
                return "add-copy-field"

    def to_dict(self) -> dict[str, Any]:
        """Return the dict representation for this schema command."""
        match self.value:
            case Field() as f:
                return f.to_dict()

            case FieldType() as f:
                return f.to_dict()

            case DynamicFieldRule() as f:
                return f.to_dict()

            case CopyFieldRule() as f:
                return f.to_dict()


@dataclass
@final
class ReplaceCommand(SchemaCommand):
    """Replace a field, field type or dynamic field.

    Use this with care if you are changing the field type.
    We have seen issues when we use this command to change the field type
    that do not occur if you call 'delete' and then 'add' rather than just 'replace'.
    """

    value: FieldType | Field | DynamicFieldRule

    def command_name(self) -> str:
        """Return the command name."""
        match self.value:
            case Field():
                return "replace-field"
            case FieldType():
                return "replace-field-type"
            case DynamicFieldRule():
                return "replace-dynamic-field"

    def to_dict(self) -> dict[str, Any]:
        """Return the dict representation for this schema command."""
        match self.value:
            case Field() as f:
                return f.to_dict()
            case FieldType() as f:
                return f.to_dict()
            case DynamicFieldRule() as f:
                return f.to_dict()


@dataclass
@final
class DeleteFieldCommand(SchemaCommand):
    """Delete a field."""

    name: FieldName

    def command_name(self) -> str:
        """Return the command name."""
        return "delete-field"

    def to_dict(self) -> dict[str, Any]:
        """Return the dict representation for this schema command."""
        return {"name": self.name}


@dataclass
@final
class DeleteFieldTypeCommand(SchemaCommand):
    """Delete a field type."""

    name: TypeName

    def command_name(self) -> str:
        """Return the command name."""
        return "delete-field-type"

    def to_dict(self) -> dict[str, Any]:
        """Return the dict representation for this schema command."""
        return {"name": self.name}


@dataclass
@final
class DeleteDynamicFieldCommand(SchemaCommand):
    """Delete a dynamic field."""

    name: FieldName

    def command_name(self) -> str:
        """Return the command name."""
        return "delete-dynamic-field"

    def to_dict(self) -> dict[str, Any]:
        """Return the dict representation for this schema command."""
        return {"name": self.name}


@dataclass
@final
class DeleteCopyFieldCommand(SchemaCommand):
    """Delete a copy field rule."""

    source: FieldName
    dest: FieldName

    def command_name(self) -> str:
        """Return the command name."""
        return "delete-copy-field"

    def to_dict(self) -> dict[str, Any]:
        """Return the dict representation for this schema command."""
        return {"source": self.source, "dest": self.dest}


@dataclass
@final
class SchemaCommandList:
    """A list of `SchemaCommand`s that provide a to_json method as expected by the solr schema api."""

    value: list[SchemaCommand]

    def is_not_empty(self) -> bool:
        """The command list is non empty."""
        return not self.value

    def is_empty(self) -> bool:
        """The command list is empty."""
        return not self.is_not_empty()

    def to_json(self) -> str:
        """Return the JSON for all schema commands.

        Solr uses multiple same named keys in a JSON object to refer to multiple schema
        commands. So this implementation is a bit awkward to produce the required format.
        """
        result = "{"
        for e in self.value:
            result += '"' + e.command_name() + '":'
            result += json.dumps(e.to_dict())
            result += ","

        result = result[:-1] + "}"
        return result


@final
class CoreSchema(BaseModel):
    """The complete schema of a solr core."""

    name: str
    version: float
    uniqueKey: FieldName
    fieldTypes: list[FieldType] = pydantic.Field(default_factory=list)
    fields: list[Field] = pydantic.Field(default_factory=list)
    dynamicFields: list[DynamicFieldRule] = pydantic.Field(default_factory=list)
    copyFields: list[CopyFieldRule] = pydantic.Field(default_factory=list)
