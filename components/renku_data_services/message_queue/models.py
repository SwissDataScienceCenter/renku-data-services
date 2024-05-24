"""Basic models used for communication with the message queue."""

import glob
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Generic, TypeVar

from dataclasses_avroschema.schema_generator import AvroModel
from dataclasses_avroschema.utils import standardize_custom_type
from fastavro import parse_schema, schemaless_reader, schemaless_writer
from ulid import ULID

from renku_data_services.message_queue.avro_models.io.renku.events.v1.header import Header

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


def _serialize_binary(obj: AvroModel) -> bytes:
    """Serialize a message with avro, making sure to use the original schema."""
    schema = parse_schema(schema=json.loads(getattr(obj, "_schema", obj.avro_schema())), named_schemas=_schemas)
    fo = BytesIO()
    schemaless_writer(fo, schema, obj.asdict(standardize_factory=standardize_custom_type))
    return fo.getvalue()


TAvro = TypeVar("TAvro", bound=AvroModel)


def deserialize_binary(data: bytes, model: type[TAvro]) -> TAvro:
    """Deserialize an avro binary message, using the original schema."""
    input_stream = BytesIO(data)
    schema = parse_schema(schema=json.loads(getattr(model, "_schema", model.avro_schema())), named_schemas=_schemas)

    payload = schemaless_reader(input_stream, schema, schema)
    input_stream.flush()
    obj = model.parse_obj(payload)  # type: ignore

    return obj


def _create_header(
    message_type: str, content_type: str = "application/avro+binary", schema_version: str = "1"
) -> Header:
    """Create a message header."""
    return Header(
        type=message_type,
        source="renku-data-services",
        dataContentType=content_type,
        schemaVersion=schema_version,
        time=datetime.now(UTC),
        requestId=ULID().hex,
    )


_EventPayloadType = TypeVar("_EventPayloadType", AvroModel, dict[str, Any])


@dataclass
class Event(Generic[_EventPayloadType]):
    """An event that should be sent to the message queue."""

    queue: str
    payload: _EventPayloadType

    def serialize(self, schema_version: str = "2") -> dict[str, Any]:
        """Create the avro message payload from the event."""
        if isinstance(self.payload, dict):
            return self.payload
        message_id = ULID().hex
        headers = _create_header(self.queue, schema_version=schema_version).serialize_json()
        message: dict[str, Any] = {
            "id": message_id,
            "headers": headers,
            "payload": _serialize_binary(self.payload),
        }
        return message
