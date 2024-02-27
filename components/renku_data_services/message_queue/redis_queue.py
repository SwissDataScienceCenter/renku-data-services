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
from renku_data_services.message_queue.avro_models.io.renku.events.v1.project_created import ProjectCreated
from renku_data_services.message_queue.avro_models.io.renku.events.v1.visibility import Visibility as MsgVisibility
from renku_data_services.message_queue.config import RedisConfig
from renku_data_services.message_queue.interface import IMessageQueue, MessageContext
from renku_data_services.project.apispec import Visibility
from renku_data_services.project.orm import ProjectRepositoryORM

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
        repositories: list[ProjectRepositoryORM],
        description: str | None,
        creation_date: datetime,
        created_by: str,
        members: list[str],
    ) -> MessageContext:
        """Event for when a new project is created."""
        headers = self._create_header("project.created")
        message_id = ULID().hex
        match visibility:
            case Visibility.private | Visibility.private.value:
                vis = MsgVisibility.PRIVATE
            case Visibility.public | Visibility.public.value:
                vis = MsgVisibility.PUBLIC
            case _:
                raise NotImplementedError(f"unknown visibility:{visibility}")
        body = ProjectCreated(
            id=id,
            name=name,
            slug=slug,
            repositories=[r.url for r in repositories],
            visibility=vis,
            description=description,
            createdBy=created_by,
            creationDate=creation_date,
            members=members,
        )

        message: dict[bytes | memoryview | str | int | float, bytes | memoryview | str | int | float] = {
            "id": message_id,
            "headers": headers.serialize_json(),
            "payload": base64.b64encode(serialize_binary(body)).decode(),
        }

        return MessageContext(self, "project.created", message)  # type:ignore

    async def send_message(
        self,
        channel: str,
        message: dict[bytes | memoryview | str | int | float, bytes | memoryview | str | int | float],
    ):
        """Send a message on a channel."""
        if "payload" in message:
            message["payload"] = base64.b64decode(message["payload"])  # type: ignore

        await self.config.redis_connection.xadd(channel, message)
