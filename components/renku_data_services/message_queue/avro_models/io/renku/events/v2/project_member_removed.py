from dataclasses import asdict, dataclass
from typing import ClassVar, Dict

from dataclasses_avroschema import AvroModel
from undictify import type_checked_constructor


@type_checked_constructor()
@dataclass
class ProjectMemberRemoved(AvroModel):
    """
    Event raised when a user is removed from a project
    """
    projectId: str
    userId: str

    #: The Avro Schema associated to this class
    _schema: ClassVar[str] = """{
        "type": "record",
        "name": "ProjectMemberRemoved",
        "namespace": "io.renku.events.v2",
        "doc": "Event raised when a user is removed from a project",
        "fields": [
            {
                "name": "projectId",
                "type": "string"
            },
            {
                "name": "userId",
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
    ) -> 'ProjectMemberRemoved':
        """
        Returns an instance of this class from a dictionary.

        :param the_dict: The dictionary from which to create an instance of this class.
        """
        return cls(**the_dict)
