from dataclasses import asdict, dataclass
from datetime import datetime
from typing import ClassVar, Dict

from dataclasses_avroschema import AvroModel
from undictify import type_checked_constructor


@type_checked_constructor()
@dataclass
class Header(AvroModel):
    """
    common headers for messages
    """
    source: str
    type: str
    dataContentType: str
    schemaVersion: str
    time: datetime  # logicalType: timestamp-millis
    requestId: str

    #: The Avro Schema associated to this class
    _schema: ClassVar[str] = """{
        "type": "record",
        "name": "Header",
        "namespace": "io.renku.v1",
        "doc": "common headers for messages",
        "fields": [
            {
                "name": "source",
                "type": "string"
            },
            {
                "name": "type",
                "type": "string"
            },
            {
                "name": "dataContentType",
                "type": "string"
            },
            {
                "name": "schemaVersion",
                "type": "string"
            },
            {
                "name": "time",
                "type": {
                    "type": "long",
                    "logicalType": "timestamp-millis"
                }
            },
            {
                "name": "requestId",
                "type": "string"
            }
        ]
    }"""

    def serialize_json(self) -> str:
        """
        Returns an Avro-json representation of this instance.
        """
        return self.serialize(serialization_type='avro-json').decode('ascii')

    def to_dict(self) -> Dict:
        """
        Returns a dictionary version of this instance.
        """
        return asdict(self)

    @classmethod
    def from_dict(
            cls,
            the_dict: Dict
    ) -> 'Header':
        """
        Returns an instance of this class from a dictionary.

        :param the_dict: The dictionary from which to create an instance of this class.
        """
        return cls(**the_dict)
