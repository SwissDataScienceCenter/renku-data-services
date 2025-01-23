"""Schema modification for solr."""

from dataclasses import dataclass
from dataclasses_json import dataclass_json

@dataclass_json
@dataclass
class Tokenizer:
    name: str

@dataclass_json
@dataclass
class Filter:
    name: str
    settings: dict

@dataclass_json
@dataclass
class Analyzer:
    tokenizer: Tokenizer
    filters: list[Filter]

@dataclass_json
@dataclass
class Fieldtype:
    name: str
    classz: str
    index_analyzer: Analyzer| None
    query_analyzer: Analyzer | None
    required: bool = False
    indexed: bool = False
    stored: bool = True
    multi_valued: bool = False
    uninvertible: bool = False
    doc_values: bool = False
    sort_missing_last: bool = True
