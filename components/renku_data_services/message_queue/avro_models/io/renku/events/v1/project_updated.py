from dataclasses import asdict, dataclass
from typing import ClassVar, Dict, List, Optional

from dataclasses_avroschema import AvroModel
from renku_data_services.message_queue.avro_models.io.renku.events.v1 import \
    Visibility
from undictify import type_checked_constructor


@type_checked_constructor()
@dataclass
class ProjectUpdated(AvroModel):
    """
    Event raised when a project is updated
    """
    id: str
    name: str
    slug: str
    repositories: List[str]
    visibility: Visibility
    description: Optional[str]
    keywords: List[str]

    #: The Avro Schema associated to this class
    _schema: ClassVar[str] = """{
        "type": "record",
        "name": "ProjectUpdated",
        "namespace": "io.renku.events.v1",
        "doc": "Event raised when a project is updated",
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
                "type": "io.renku.events.v1.Visibility"
            },
            {
                "name": "description",
                "type": [
                    "null",
                    "string"
                ]
            },
            {
                "name": "keywords",
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
    ) -> 'ProjectUpdated':
        """
        Returns an instance of this class from a dictionary.

        :param the_dict: The dictionary from which to create an instance of this class.
        """
        return cls(**the_dict)
