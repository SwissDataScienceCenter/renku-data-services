"""Message queue implementation for redis streams."""

import base64
import copy
import glob
import json
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from io import BytesIO
from pathlib import Path
from typing import TypeVar

from dataclasses_avroschema.schema_generator import AvroModel
from dataclasses_avroschema.utils import standardize_custom_type
from fastavro import parse_schema, schemaless_reader, schemaless_writer
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from renku_data_services.message_queue import AmbiguousEvent
from renku_data_services.message_queue.avro_models.io.renku.events.v1.header import Header
from renku_data_services.message_queue.config import RedisConfig
from renku_data_services.message_queue.converters import EventConverter
from renku_data_services.message_queue.interface import IMessageQueue

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


def deserialize_binary(data: bytes, model: type[T]) -> T:
    """Deserialize an avro binary message, using the original schema."""
    input_stream = BytesIO(data)
    schema = parse_schema(schema=json.loads(getattr(model, "_schema", model.avro_schema())), named_schemas=_schemas)

    payload = schemaless_reader(input_stream, schema, schema)
    input_stream.flush()
    obj = model.parse_obj(payload)  # type: ignore

    return obj


def create_header(
    message_type: str, content_type: str = "application/avro+binary", schema_version: str = "1"
) -> Header:
    """Create a message header."""
    return Header(
        type=message_type,
        source="renku-data-services",
        dataContentType=content_type,
        schemaVersion=schema_version,
        time=datetime.utcnow(),
        requestId=ULID().hex,
    )


def dispatch_message(event_type: type[AvroModel] | AmbiguousEvent):
    """Sends a message on the message queue.

    The transform method is called with the arguments and result of the wrapped method. It is responsible for
    creating the message type to dispatch. The message is sent based on the return type of the transform method.
    Messages are stored in the database in the same transaction as the changed entities, and are sent by a background
    job to ensure delivery of messages and prevent messages being sent in case of failing transactions or due to
    exceptions.
    """

    def decorator(f):
        @wraps(f)
        async def message_wrapper(self, session: AsyncSession, *args, **kwargs):
            result = await f(self, session, *args, **kwargs)
            if result is None:
                return result
            events = EventConverter.to_events(result, event_type)

            for event in events:
                message_id = ULID().hex
                schema_version = "2" if event_type == AmbiguousEvent.PROJECT_MEMBERSHIP_CHANGED else "1"
                headers = create_header(event.queue, schema_version=schema_version).serialize_json()
                message: dict[bytes | memoryview | str | int | float, bytes | memoryview | str | int | float] = {
                    "id": message_id,
                    "headers": headers,
                    "payload": base64.b64encode(serialize_binary(event.payload)).decode(),
                }
                await self.event_repo.store_event(session, event.queue, message)

            return result

        return message_wrapper

    return decorator


@dataclass
class RedisQueue(IMessageQueue):
    """Redis streams queue implementation."""

    config: RedisConfig

    async def send_message(
        self,
        channel: str,
        message: dict[bytes | memoryview | str | int | float, bytes | memoryview | str | int | float],
    ):
        """Send a message on a channel."""
        message = copy.copy(message)
        if "payload" in message:
            message["payload"] = base64.b64decode(message["payload"])  # type: ignore

        await self.config.redis_connection.xadd(channel, message)
