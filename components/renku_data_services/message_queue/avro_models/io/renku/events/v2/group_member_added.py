from dataclasses import asdict, dataclass
from typing import ClassVar, Dict

from dataclasses_avroschema import AvroModel
from renku_data_services.message_queue.avro_models.io.renku.events.v2 import \
    MemberRole
from undictify import type_checked_constructor


@type_checked_constructor()
@dataclass
class GroupMemberAdded(AvroModel):
    """
    Event raised when a member is added to a group
    """
    groupId: str
    userId: str
    role: MemberRole

    #: The Avro Schema associated to this class
    _schema: ClassVar[str] = """{
        "type": "record",
        "name": "GroupMemberAdded",
        "namespace": "io.renku.events.v2",
        "doc": "Event raised when a member is added to a group",
        "fields": [
            {
                "name": "groupId",
                "type": "string"
            },
            {
                "name": "userId",
                "type": "string"
            },
            {
                "name": "role",
                "type": "io.renku.events.v2.MemberRole"
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
    ) -> 'GroupMemberAdded':
        """
        Returns an instance of this class from a dictionary.

        :param the_dict: The dictionary from which to create an instance of this class.
        """
        return cls(**the_dict)
