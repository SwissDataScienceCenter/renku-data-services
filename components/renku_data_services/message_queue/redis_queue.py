"""Message queue implementation for redis streams."""

import base64
import copy
import glob
import inspect
import json
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from io import BytesIO
from pathlib import Path
from types import NoneType, UnionType
from typing import Callable, Optional, Type, TypeVar, Union

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
from renku_data_services.message_queue.avro_models.io.renku.events.v1.project_removed import ProjectRemoved
from renku_data_services.message_queue.avro_models.io.renku.events.v1.project_updated import ProjectUpdated
from renku_data_services.message_queue.avro_models.io.renku.events.v1.user_added import UserAdded
from renku_data_services.message_queue.avro_models.io.renku.events.v1.user_removed import UserRemoved
from renku_data_services.message_queue.avro_models.io.renku.events.v1.user_updated import UserUpdated
from renku_data_services.message_queue.config import RedisConfig
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


def deserialize_binary(data: bytes, model: Type[T]) -> T:
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


def dispatch_message(transform: Callable[..., Union[AvroModel, Optional[AvroModel]]]):
    """Sends a message on the message queue.

    The transform method is called with the arguments and result of the wrapped method. It is responsible for
    creating the message type to dispatch. The message is sent based on the return type of the transform method.
    This wrapper takes care of guaranteed at-least-once delivery of messages by using a backup 'events' table that
    stores messages for redelivery shold sending fail.
    """

    def decorator(f):
        @wraps(f)
        async def message_wrapper(self, session, *args, **kwargs):
            result = await f(self, session, *args, **kwargs)
            payload = transform(result, *args, **kwargs)

            if payload is None:
                # don't send message if transform returned None
                return result

            signature = inspect.signature(transform).return_annotation

            # Handle type unions
            non_none_types = None
            if isinstance(signature, UnionType):
                non_none_types = [t for t in signature.__args__ if t != NoneType]
            elif isinstance(signature, str) and " | " in signature:
                non_none_types = [t for t in signature.split(" | ") if t != "None"]

            if non_none_types is not None:
                if len(non_none_types) != 1:
                    raise NotImplementedError(f"Only optional types are supported, got {signature}")
                signature = non_none_types[0]
            if not isinstance(signature, str):
                # depending on 'from _future_ import annotations' this can be a string or a type
                signature = signature.__qualname__

            match signature:
                case ProjectCreated.__qualname__:
                    queue_name = "project.created"
                case ProjectUpdated.__qualname__:
                    queue_name = "project.updated"
                case ProjectRemoved.__qualname__:
                    queue_name = "project.removed"
                case UserAdded.__qualname__:
                    queue_name = "user.added"
                case UserUpdated.__qualname__:
                    queue_name = "user.updated"
                case UserRemoved.__qualname__:
                    queue_name = "user.removed"
                case ProjectAuthorizationAdded.__qualname__:
                    queue_name = "projectAuth.added"
                case ProjectAuthorizationUpdated.__qualname__:
                    queue_name = "projectAuth.updated"
                case ProjectAuthorizationRemoved.__qualname__:
                    queue_name = "projectAuth.removed"
                case _:
                    raise NotImplementedError(f"Can't create message using transform {transform}:{signature}")
            headers = create_header(queue_name)
            message_id = ULID().hex
            message: dict[bytes | memoryview | str | int | float, bytes | memoryview | str | int | float] = {
                "id": message_id,
                "headers": headers.serialize_json(),
                "payload": base64.b64encode(serialize_binary(payload)).decode(),
            }
            event_id = await self.event_repo.store_event(session, queue_name, message)
            session.commit()

            try:
                await self.message_queue.send_message(queue_name, message)
            except:  # noqa:E722
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
