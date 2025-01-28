"""Schema modification for solr."""

from abc import abstractmethod
from dataclasses import dataclass
from pydantic import BaseModel, model_serializer
from typing import NewType, final, Self, Any
import json

import pydantic



TypeName = NewType("TypeName", str)
FieldName = NewType("FieldName", str)


class SchemaModel(BaseModel):
    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_defaults=True)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

@final
class Tokenizer(SchemaModel):
    name: TypeName


@final
class Filter(BaseModel):
    """Defines a SOLR filter. See https://solr.apache.org/guide/solr/latest/indexing-guide/filters.html."""

    name: str
    settings: dict | None = None

    @model_serializer()
    def to_dict(self) -> dict[str, Any]:
        match self.settings:
            case None:
                return {"name":self.name}
            case _:
                data = self.settings.copy()
                data.update({"name": self.name})
                return data



@final
class Filters:
    """A list of predefined filters supported by SOLR."""

    ascii_folding = Filter(name = "asciiFolding")
    lowercase = Filter(name = "lowercase")
    stop = Filter(name = "stop")
    english_minimal_stem = Filter(name="englishMinimalStem")
    classic = Filter(name="classic")
    ngram = Filter(name="nGram")

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
class Analyzer(SchemaModel):
    tokenizer: Tokenizer
    filters: list[Filter] = pydantic.Field(default_factory=list)


FieldTypeClass = NewType("FieldTypeClass", str)


class FieldTypeClasses:
    """A list of field type classses."""

    type_int = FieldTypeClass("IntPointField")
    type_long = FieldTypeClass("LongPointField")
    type_float = FieldTypeClass("FloatPointField")
    type_double = FieldTypeClass("DoublePointField")
    type_text = FieldTypeClass("TextField")
    type_str = FieldTypeClass("StrField")
    type_uuid = FieldTypeClass("UUIDField")
    type_rank = FieldTypeClass("RankField")
    type_date_point = FieldTypeClass("DatePointField")
    type_date_range = FieldTypeClass("DateRangeField")
    type_bool = FieldTypeClass("BoolField")


@final
class FieldType(SchemaModel):
    name: TypeName
    clazz: FieldTypeClass = pydantic.Field(serialization_alias="class")
    index_analyzer: Analyzer | None = None
    query_analyzer: Analyzer | None = None
    required: bool = False
    indexed: bool = False
    stored: bool = True
    multi_valued: bool = False
    uninvertible: bool = False
    doc_values: bool = False
    sort_missing_last: bool = True

    @classmethod
    def id(cls, name: TypeName) -> Self:
        """Create a field that can be used as a document id."""
        return FieldType(name=name, clazz=FieldTypeClasses.type_str)

    @classmethod
    def text(cls, name: TypeName) -> Self:
        return FieldType(name=name, clazz=FieldTypeClasses.type_text)

    @classmethod
    def str(cls, name: TypeName) -> Self:
        return FieldType(name=name, clazz=FieldTypeClasses.type_str)

    @classmethod
    def int(cls, name: TypeName) -> Self:
        return FieldType(name=name, clazz=FieldTypeClasses.type_int)

    @classmethod
    def long(cls, name: TypeName) -> Self:
        return FieldType(name=name, clazz=FieldTypeClasses.type_long)

    @classmethod
    def double(cls, name: TypeName) -> Self:
        return FieldType(name=name, clazz=FieldTypeClasses.type_double)

    @classmethod
    def dateTime(cls, name: TypeName) -> Self:
        return FieldType(name=name, clazz=FieldTypeClasses.type_date_range)


@final
class Field(SchemaModel):
    name: FieldName
    type: TypeName
    required: bool = False
    indexed: bool = True
    stored: bool = True
    multiValued: bool = False
    uninvertible: bool = True
    docValues: bool = False

    @classmethod
    def of(cls, name: FieldName, type: FieldType) -> Self:
        return Field(name=name, type=type.name)


@final
class DynamicFieldRule(SchemaModel):
    name: FieldName
    type: TypeName
    required: bool = False
    indexed: bool = True
    stored: bool = True
    multiValued: bool = False
    uninvertible: bool = False
    docValues: bool = False


@final
class CopyFieldRule(SchemaModel):
    source: FieldName
    dest: FieldName
    maxChars: int | None = None


class SchemaCommand:
    @abstractmethod
    def to_dict(self) -> dict[str, Any]: ...

    @abstractmethod
    def command_name(self) -> str: ...


@dataclass
@final
class AddCommand:
    value: Field | FieldType | DynamicFieldRule | CopyFieldRule

    def command_name(self) -> str:
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
class SchemaCommandList:
    value: list[SchemaCommand]

    def to_json(self) -> str:
        result = "{"
        for e in self.value:
            result += '"' + e.command_name() + '":'
            result += json.dumps(e.to_dict())
            result += ","

        result = result[:-1] + "}"
        return result
