from dataclasses import asdict, dataclass
from typing import ClassVar, Dict

from dataclasses_avroschema import AvroModel
from renku_data_services.message_queue.avro_models.io.renku.events.v1 import \
    ProjectMemberRole
from undictify import type_checked_constructor


@type_checked_constructor()
@dataclass
class ProjectAuthorizationUpdated(AvroModel):
    """
    Event raised when an authorization for a project is modified
    """
    projectId: str
    userId: str
    role: ProjectMemberRole

    #: The Avro Schema associated to this class
    _schema: ClassVar[str] = """{
        "type": "record",
        "name": "ProjectAuthorizationUpdated",
        "namespace": "io.renku.events.v1",
        "doc": "Event raised when an authorization for a project is modified",
        "fields": [
            {
                "name": "projectId",
                "type": "string"
            },
            {
                "name": "userId",
                "type": "string"
            },
            {
                "name": "role",
                "type": "io.renku.events.v1.ProjectMemberRole"
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
    ) -> 'ProjectAuthorizationUpdated':
        """
        Returns an instance of this class from a dictionary.

        :param the_dict: The dictionary from which to create an instance of this class.
        """
        return cls(**the_dict)
