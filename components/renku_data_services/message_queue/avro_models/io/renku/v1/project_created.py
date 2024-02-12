from dataclasses import asdict, dataclass
from datetime import datetime
from typing import ClassVar, Dict, List, Optional

from dataclasses_avroschema import AvroModel
from undictify import type_checked_constructor

from renku_data_services.message_queue.avro_models.io.renku.v1 import Visibility


@type_checked_constructor()
@dataclass
class ProjectCreated(AvroModel):
    id: str
    name: str
    slug: str
    repositories: List[str]
    visibility: Visibility
    description: Optional[str]
    createdBy: str
    creationDate: datetime  # logicalType: timestamp-millis
    members: List[str]

    #: The Avro Schema associated to this class
    _schema: ClassVar[
        str
    ] = """{
        "type": "record",
        "name": "ProjectCreated",
        "namespace": "io.renku.v1",
        "fields": [
            {
                "name": "id",
                "type": "string"
            },
            {
                "name": "name",
                "type": "string"
            },
            {
                "name": "slug",
                "type": "string"
            },
            {
                "name": "repositories",
                "type": {
                    "type": "array",
                    "items": "string"
                },
                "default": []
            },
            {
                "name": "visibility",
                "type": "io.renku.v1.Visibility"
            },
            {
                "name": "description",
                "type": [
                    "null",
                    "string"
                ]
            },
            {
                "name": "createdBy",
                "type": "string"
            },
            {
                "name": "creationDate",
                "type": {
                    "type": "long",
                    "logicalType": "timestamp-millis"
                }
            },
            {
                "name": "members",
                "type": {
                    "type": "array",
                    "items": "string"
                },
                "default": []
            }
        ]
    }"""

    def serialize_json(self) -> str:
        """
        Returns an Avro-json representation of this instance.
        """
        return self.serialize(serialization_type="avro-json").decode("ascii")

    def to_dict(self) -> Dict:
        """
        Returns a dictionary version of this instance.
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, the_dict: Dict) -> "ProjectCreated":
        """
        Returns an instance of this class from a dictionary.

        :param the_dict: The dictionary from which to create an instance of this class.
        """
        return cls(**the_dict)
