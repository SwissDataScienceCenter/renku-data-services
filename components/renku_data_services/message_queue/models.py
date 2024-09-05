"""Basic models used for communication with the message queue."""

import glob
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Self, TypeVar

from dataclasses_avroschema.schema_generator import AvroModel
from dataclasses_avroschema.utils import standardize_custom_type
from fastavro import parse_schema, schemaless_reader, schemaless_writer
from ulid import ULID

from renku_data_services.message_queue.avro_models.io.renku.events.v1.header import Header

_root: Path = Path(__file__).parent.resolve()
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
    message_type: str, content_type: str = "application/avro+binary", schema_version: str = "2"
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


@dataclass
class Event:
    """An event and the queue it is supposed to be sent to."""

    queue: str
    _payload: dict[str, Any]

    def serialize(self) -> dict[str, Any]:
        """Return the event as avro payload."""
        return self._payload

    @classmethod
    def create(cls, queue: str, message_type: str, payload: AvroModel) -> Self:
        """Create a new event from an avro model."""
        message_id = ULID().hex
        headers = _create_header(message_type, schema_version="2").serialize_json()
        message: dict[str, Any] = {
            "id": message_id,
            "headers": headers,
            "payload": _serialize_binary(payload),
        }
        return cls(queue, message)
