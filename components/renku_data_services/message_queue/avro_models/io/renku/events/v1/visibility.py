from enum import Enum
from typing import ClassVar


class Visibility(Enum):
    """
    Visibility setting
    """
    PUBLIC = 'PUBLIC'
    PRIVATE = 'PRIVATE'

    #: The Avro Schema associated to this class
    _schema: ClassVar[str] = """{
        "type": "enum",
        "name": "Visibility",
        "doc": "Visibility setting",
        "namespace": "io.renku.events.v1",
        "symbols": [
            "PUBLIC",
            "PRIVATE"
        ]
    }"""
