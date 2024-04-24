"""Message queue implementation for redis streams."""

import base64
import copy
import glob
import json
import logging
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
from renku_data_services.message_queue.avro_models.io.renku.events import v1, v2
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


def create_header(message_type: str, content_type: str = "application/avro+binary") -> Header:
    """Create a message header."""
    return Header(
        type=message_type,
        source="renku-data-services",
        dataContentType=content_type,
        schemaVersion="1",
        time=datetime.utcnow(),
        requestId=ULID().hex,
    )

def dispatch_message(event_type: type[AvroModel] | AmbiguousEvent):
    """Sends a message on the message queue.

    The transform method is called with the arguments and result of the wrapped method. It is responsible for
    creating the message type to dispatch. The message is sent based on the return type of the transform method.
    This wrapper takes care of guaranteed at-least-once delivery of messages by using a backup 'events' table that
    stores messages for redelivery shold sending fail. For this to work correctly, the messages need to be stored
    in the events table in the same database transaction as the metadata update that they are related to.
    All this is to ensure that downstream consumers are kept up to date. They are expected to handle multiple
    delivery of the same message correctly.
    This code addresses these potential error cases:
    - Data being persisted in our database but no message being sent due to errors/restarts of the service at the
      wrong time.
    - Redis not being available.
    Downstream consumers are expected to handle the following:
    - The same message being delivered more than once. Deduplication can be done due to the message ids being
      the identical.
    - Messages being delivered out of order. This should be super rare, e.g. a user edits a project, message delivery
      fails duf to redis being down, the user then deletes the project and message delivery works. Then the first
      message is delivered again and this works, meaning downstream the project deletion arrives before the project
      update. Order can be maintained due to the timestamps in the messages.
    """

    def decorator(f):
        @wraps(f)
        async def message_wrapper(self, session: AsyncSession, *args, **kwargs):
            result = await f(self, session, *args, **kwargs)
            if result is None:
                return result
            payloads = EventConverter.to_event(result, event_type)

            match event_type:
                case v1.ProjectCreated | v2.ProjectCreated:
                    queue_name = "project.created"
                case v1.ProjectUpdated | v2.ProjectUpdated:
                    queue_name = "project.updated"
                case v1.ProjectRemoved | v2.ProjectRemoved:
                    queue_name = "project.removed"
                case v1.UserAdded | v2.UserUpdated:
                    queue_name = "user.added"
                case v1.UserUpdated | v2.UserUpdated:
                    queue_name = "user.updated"
                case v1.UserRemoved | v2.UserRemoved:
                    queue_name = "user.removed"
                case AmbiguousEvent.PROJECT_MEMBERSHIP_CHANGED:
                    queue_name = "to_be_determined_later"
                case v2.ProjectMemberRemoved:
                    queue_name = "projectAuth.removed"
                case _:
                    raise NotImplementedError(f"Can't find queue name for event type {event_type}")
            for payload in payloads:
                if isinstance(payload, v2.ProjectMemberUpdated):
                    queue_name = "projectAuth.updated"
                elif isinstance(payload, v2.ProjectMemberAdded):
                    queue_name = "projectAuth.added"
                elif isinstance(payload, v2.ProjectMemberRemoved):
                    queue_name = "projectAuth.removed"
                message_id = ULID().hex
                headers = create_header(queue_name).serialize_json()
                message: dict[bytes | memoryview | str | int | float, bytes | memoryview | str | int | float] = {
                    "id": message_id,
                    "headers": headers,
                    "payload": base64.b64encode(serialize_binary(payload)).decode(),
                }
                event_id = await self.event_repo.store_event(session, queue_name, message)

                try:
                    await self.message_queue.send_message(queue_name, message)
                except Exception as err:
                    logging.warning(
                        f"Could not insert event message to redis queue because of {err} "
                        "events have been added to postgres, will attempt to send them later."
                    )
                    return result
                await self.event_repo.delete_event(event_id)
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
