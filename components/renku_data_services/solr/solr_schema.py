"""Schema modification for solr."""

from abc import abstractmethod
from dataclasses import dataclass, field
from dataclasses_json import dataclass_json, config
from typing import NewType, final, Self, Any
import json


def _excludeWhen(v):
    return lambda x: x == v


TypeName = NewType("TypeName", str)
FieldName = NewType("FieldName", str)


@dataclass_json
@dataclass
@final
class Tokenizer:
    name: TypeName



@dataclass
@final
class Filter:
    """Defines a SOLR filter. See https://solr.apache.org/guide/solr/latest/indexing-guide/filters.html."""

    name: str
    settings: dict | None = field(metadata=config(exclude=lambda v: v is None), default=None)

    def to_json(self) -> str:
        match self.settings:
            case None:
                return json.dumps({"name":self.name})
            case _:
                data = self.settings.copy()
                data.update({"name": self.name})
                return json.dumps(data)

@final
class Filters:
    """A list of predefined filters supported by SOLR."""

    ASCII_FOLDING = Filter("asciiFolding")
    LOWERCASE = Filter("lowercase")
    STOP = Filter("stop")
    ENGLISH_MINIMAL_STEM = Filter("englishMinimalStem")
    CLASSIC = Filter("classic")
    NGRAM = Filter("nGram")

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


@dataclass_json
@dataclass
@final
class Analyzer:
    tokenizer: Tokenizer
    filters: list[Filter] = field(default_factory=list)


FieldTypeClass = NewType("FieldTypeClass", str)


# look if enum makes sense
class FieldTypeClasses:
    """A list of field type classses."""

    type_int = FieldTypeClass("IntPointField")
    TYPE_LONG = FieldTypeClass("LongPointField")
    TYPE_FLOAT = FieldTypeClass("FloatPointField")
    TYPE_DOUBLE = FieldTypeClass("DoublePointField")
    TYPE_TEXT = FieldTypeClass("TextField")
    TYPE_STR = FieldTypeClass("StrField")
    TYPE_UUID = FieldTypeClass("UUIDField")
    TYPE_RANK = FieldTypeClass("RankField")
    TYPE_DATE_POINT = FieldTypeClass("DatePointField")
    TYPE_DATE_RANGE = FieldTypeClass("DateRangeField")
    TYPE_BOOL = FieldTypeClass("BoolField")


@dataclass_json
@dataclass
@final
class FieldType:
    name: TypeName
    clazz: FieldTypeClass = field(metadata=config(field_name="class"))
    index_analyzer: Analyzer | None = field(metadata=config(exclude=_excludeWhen(None)), default=None)
    query_analyzer: Analyzer | None = field(metadata=config(exclude=_excludeWhen(None)), default=None)
    required: bool = field(metadata=config(exclude=_excludeWhen(False)), default=False)
    indexed: bool = field(metadata=config(exclude=_excludeWhen(False)), default=False)
    stored: bool = field(metadata=config(exclude=_excludeWhen(True)), default=True)
    multi_valued: bool = field(metadata=config(exclude=_excludeWhen(False)), default=False)
    uninvertible: bool = field(metadata=config(exclude=_excludeWhen(False)), default=False)
    doc_values: bool = field(metadata=config(exclude=_excludeWhen(False)), default=False)
    sort_missing_last: bool = field(metadata=config(exclude=_excludeWhen(True)), default=True)

    @classmethod
    def id(cls, name: TypeName) -> Self:
        """Create a field that can be used as a document id."""
        return FieldType(name, FieldTypeClasses.TYPE_STR)

    @classmethod
    def text(cls, name: TypeName) -> Self:
        return FieldType(name, FieldTypeClasses.TYPE_TEXT)

    @classmethod
    def str(cls, name: TypeName) -> Self:
        return FieldType(name, FieldTypeClasses.TYPE_STR)

    @classmethod
    def int(cls, name: TypeName) -> Self:
        return FieldType(name, FieldTypeClasses.TYPE_INT)

    @classmethod
    def long(cls, name: TypeName) -> Self:
        return FieldType(name, FieldTypeClasses.TYPE_LONG)

    @classmethod
    def double(cls, name: TypeName) -> Self:
        return FieldType(name, FieldTypeClasses.TYPE_DOUBLE)

    @classmethod
    def dateTime(cls, name: TypeName) -> Self:
        return FieldType(name, FieldTypeClasses.TYPE_DATE_RANGE)


@dataclass_json
@dataclass
@final
class Field:
    name: FieldName
    type: TypeName
    required: bool = field(metadata=config(exclude=_excludeWhen(False)), default=False)
    indexed: bool = field(metadata=config(exclude=_excludeWhen(True)), default=True)
    stored: bool = field(metadata=config(exclude=_excludeWhen(True)), default=True)
    multiValued: bool = field(metadata=config(exclude=_excludeWhen(False)), default=False)
    uninvertible: bool = field(metadata=config(exclude=_excludeWhen(True)), default=True)
    docValues: bool = field(metadata=config(exclude=_excludeWhen(False)), default=False)

    @classmethod
    def of(cls, name: FieldName, type: FieldType) -> Self:
        return Field(name=name, type=type.name)


@dataclass_json
@dataclass
@final
class DynamicFieldRule:
    name: FieldName
    type: TypeName
    required: bool = field(metadata=config(exclude=_excludeWhen(False)), default=False)
    indexed: bool = field(metadata=config(exclude=_excludeWhen(True)), default=True)
    stored: bool = field(metadata=config(exclude=_excludeWhen(True)), default=True)
    multiValued: bool = field(metadata=config(exclude=_excludeWhen(False)), default=False)
    uninvertible: bool = field(metadata=config(exclude=_excludeWhen(False)), default=False)
    docValues: bool = field(metadata=config(exclude=_excludeWhen(False)), default=False)


@dataclass_json
@dataclass
@final
class CopyFieldRule:
    source: FieldName
    dest: FieldName
    maxChars: int | None = field(metadata=config(exclude=_excludeWhen(None)), default=None)


class SchemaCommand:
    @abstractmethod
    def to_dict(self) -> dict[str, Any]: ...

    @abstractmethod
    def command_name(self) -> str: ...


@dataclass
@final
class AddCommand(SchemaCommand):
    value: Field | FieldType | DynamicFieldRule | CopyFieldRule

    def command_name(self) -> str:
        match self.value:
            case Field(_):
                return "add-field"

            case FieldType(_):
                return "add-field-type"

            case DynamicFieldRule(_):
                return "add-dynamic-field"

            case CopyFieldRule(_):
                return "add-copy-field"

    def to_dict(self) -> dict[str, Any]:
        match self.value:
            case Field(_) as f:
                return f.to_dict()

            case FieldType(_) as f:
                return f.to_dict()

            case DynamicFieldRule(_) as f:
                return f.to_dict()

            case CopyFieldRule(_) as f:
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
