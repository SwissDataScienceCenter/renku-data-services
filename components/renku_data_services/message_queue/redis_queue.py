"""Message queue implementation for redis streams."""

import base64
import glob
import json
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Type, TypeVar

from dataclasses_avroschema.schema_generator import AvroModel
from dataclasses_avroschema.utils import standardize_custom_type
from fastavro import parse_schema, schemaless_reader, schemaless_writer
from ulid import ULID

from renku_data_services.message_queue.avro_models.io.renku.events.v1.header import Header
from renku_data_services.message_queue.avro_models.io.renku.events.v1.project_authorization_added import (
    ProjectAuthorizationAdded,
)
from renku_data_services.message_queue.avro_models.io.renku.events.v1.project_authorization_removed import (
    ProjectAuthorizationRemoved,
)
from renku_data_services.message_queue.avro_models.io.renku.events.v1.project_authorization_updated import (
    ProjectAuthorizationUpdated,
)
from renku_data_services.message_queue.avro_models.io.renku.events.v1.project_created import ProjectCreated
from renku_data_services.message_queue.avro_models.io.renku.events.v1.project_member_role import ProjectMemberRole
from renku_data_services.message_queue.avro_models.io.renku.events.v1.project_removed import ProjectRemoved
from renku_data_services.message_queue.avro_models.io.renku.events.v1.project_updated import ProjectUpdated
from renku_data_services.message_queue.avro_models.io.renku.events.v1.user_added import UserAdded
from renku_data_services.message_queue.avro_models.io.renku.events.v1.user_removed import UserRemoved
from renku_data_services.message_queue.avro_models.io.renku.events.v1.user_updated import UserUpdated
from renku_data_services.message_queue.avro_models.io.renku.events.v1.visibility import Visibility
from renku_data_services.message_queue.config import RedisConfig
from renku_data_services.message_queue.interface import IMessageQueue, MessageContext

_root = Path(__file__).parent.resolve()
_filter = f"{_root}/schemas/**/*.avsc"
_schemas = {}
for file in glob.glob(_filter, recursive=True):
    with open(file) as f:
        _schema = json.load(f)
        if "name" in _schema:
            _name = _schema["name"]
            _namespace = _schema.get("namespace")
            if _namespace:
                _name = f"{_namespace}.{_name}"
            _schemas[_name] = _schema


def serialize_binary(obj: AvroModel) -> bytes:
    """Serialize a message with avro, making sure to use the original schema."""
    schema = parse_schema(schema=json.loads(getattr(obj, "_schema", obj.avro_schema())), named_schemas=_schemas)
    fo = BytesIO()
    schemaless_writer(fo, schema, obj.asdict(standardize_factory=standardize_custom_type))
    return fo.getvalue()


T = TypeVar("T", bound=AvroModel)


def deserialize_binary(data: bytes, model: Type[T]) -> T:
    """Deserialize an avro binary message, using the original schema."""
    input_stream = BytesIO(data)
    schema = parse_schema(schema=json.loads(getattr(model, "_schema", model.avro_schema())), named_schemas=_schemas)

    payload = schemaless_reader(input_stream, schema, schema)
    input_stream.flush()
    obj = model.parse_obj(payload)  # type: ignore

    return obj


@dataclass
class RedisQueue(IMessageQueue):
    """Redis streams queue implementation."""

    config: RedisConfig

    def _create_header(self, message_type: str, content_type: str = "application/avro+binary") -> Header:
        """Create a message header."""
        return Header(
            type=message_type,
            source="renku-data-services",
            dataContentType=content_type,
            schemaVersion="1",
            time=datetime.utcnow(),
            requestId=ULID().hex,
        )

    def project_created_message(
        self,
        name: str,
        slug: str,
        visibility: Visibility,
        id: str,
        repositories: list[str],
        description: str | None,
        creation_date: datetime,
        created_by: str,
    ) -> MessageContext:
        """Event for when a new project is created."""
        headers = self._create_header("project.created")
        message_id = ULID().hex
        body = ProjectCreated(
            id=id,
            name=name,
            slug=slug,
            repositories=repositories,
            visibility=visibility,
            description=description,
            createdBy=created_by,
            creationDate=creation_date,
        )

        message: dict[bytes | memoryview | str | int | float, bytes | memoryview | str | int | float] = {
            "id": message_id,
            "headers": headers.serialize_json(),
            "payload": base64.b64encode(serialize_binary(body)).decode(),
        }

        return MessageContext(self, "project.created", message)  # type:ignore

    def project_updated_message(
        self,
        name: str,
        slug: str,
        visibility: Visibility,
        id: str,
        repositories: list[str],
        description: str | None,
    ) -> MessageContext:
        """Event for when a new project is modified."""
        headers = self._create_header("project.updated")
        message_id = ULID().hex
        body = ProjectUpdated(
            id=id,
            name=name,
            slug=slug,
            repositories=repositories,
            visibility=visibility,
            description=description,
        )

        message: dict[bytes | memoryview | str | int | float, bytes | memoryview | str | int | float] = {
            "id": message_id,
            "headers": headers.serialize_json(),
            "payload": base64.b64encode(serialize_binary(body)).decode(),
        }

        return MessageContext(self, "project.updated", message)  # type:ignore

    def project_removed_message(
        self,
        id: str,
    ) -> MessageContext:
        """Event for when a new project is removed."""
        headers = self._create_header("project.updated")
        message_id = ULID().hex
        body = ProjectRemoved(
            id=id,
        )

        message: dict[bytes | memoryview | str | int | float, bytes | memoryview | str | int | float] = {
            "id": message_id,
            "headers": headers.serialize_json(),
            "payload": base64.b64encode(serialize_binary(body)).decode(),
        }

        return MessageContext(self, "project.removed", message)  # type:ignore

    def project_auth_added_message(self, project_id: str, user_id: str, role: ProjectMemberRole) -> MessageContext:
        """Event for when a new project authorization is created."""
        headers = self._create_header("projectAuth.added")
        message_id = ULID().hex
        body = ProjectAuthorizationAdded(
            projectId=project_id,
            userId=user_id,
            role=role,
        )

        message: dict[bytes | memoryview | str | int | float, bytes | memoryview | str | int | float] = {
            "id": message_id,
            "headers": headers.serialize_json(),
            "payload": base64.b64encode(serialize_binary(body)).decode(),
        }

        return MessageContext(self, "projectAuth.added", message)  # type:ignore

    def project_auth_updated_message(self, project_id: str, user_id: str, role: ProjectMemberRole) -> MessageContext:
        """Event for when a new project authorization is modified."""
        headers = self._create_header("projectAuth.updated")
        message_id = ULID().hex
        body = ProjectAuthorizationUpdated(
            projectId=project_id,
            userId=user_id,
            role=role,
        )

        message: dict[bytes | memoryview | str | int | float, bytes | memoryview | str | int | float] = {
            "id": message_id,
            "headers": headers.serialize_json(),
            "payload": base64.b64encode(serialize_binary(body)).decode(),
        }

        return MessageContext(self, "projectAuth.updated", message)  # type:ignore

    def project_auth_removed_message(
        self,
        project_id: str,
        user_id: str,
    ) -> MessageContext:
        """Event for when a new project authorization is removed."""
        headers = self._create_header("projectAuth.removed")
        message_id = ULID().hex
        body = ProjectAuthorizationRemoved(
            projectId=project_id,
            userId=user_id,
        )

        message: dict[bytes | memoryview | str | int | float, bytes | memoryview | str | int | float] = {
            "id": message_id,
            "headers": headers.serialize_json(),
            "payload": base64.b64encode(serialize_binary(body)).decode(),
        }

        return MessageContext(self, "projectAuth.removed", message)  # type:ignore

    def user_added_message(
        self,
        first_name: str | None,
        last_name: str | None,
        email: str | None,
        id: str,
    ) -> MessageContext:
        """Event for when a new user is created."""
        headers = self._create_header("user.added")
        message_id = ULID().hex
        body = UserAdded(id=id, firstName=first_name, lastName=last_name, email=email)

        message: dict[bytes | memoryview | str | int | float, bytes | memoryview | str | int | float] = {
            "id": message_id,
            "headers": headers.serialize_json(),
            "payload": base64.b64encode(serialize_binary(body)).decode(),
        }

        return MessageContext(self, "user.added", message)  # type:ignore

    def user_updated_message(
        self,
        first_name: str | None,
        last_name: str | None,
        email: str | None,
        id: str,
    ) -> MessageContext:
        """Event for when a new user is modified."""
        headers = self._create_header("user.updated")
        message_id = ULID().hex
        body = UserUpdated(id=id, firstName=first_name, lastName=last_name, email=email)

        message: dict[bytes | memoryview | str | int | float, bytes | memoryview | str | int | float] = {
            "id": message_id,
            "headers": headers.serialize_json(),
            "payload": base64.b64encode(serialize_binary(body)).decode(),
        }

        return MessageContext(self, "user.updated", message)  # type:ignore

    def user_removed_message(
        self,
        id: str,
    ) -> MessageContext:
        """Event for when a new user is removed."""
        headers = self._create_header("user.removed")
        message_id = ULID().hex
        body = UserRemoved(id=id)

        message: dict[bytes | memoryview | str | int | float, bytes | memoryview | str | int | float] = {
            "id": message_id,
            "headers": headers.serialize_json(),
            "payload": base64.b64encode(serialize_binary(body)).decode(),
        }

        return MessageContext(self, "user.removed", message)  # type:ignore

    async def send_message(
        self,
        channel: str,
        message: dict[bytes | memoryview | str | int | float, bytes | memoryview | str | int | float],
    ):
        """Send a message on a channel."""
        if "payload" in message:
            message["payload"] = base64.b64decode(message["payload"])  # type: ignore

        await self.config.redis_connection.xadd(channel, message)
