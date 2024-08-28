"""Tests for the EventORM class"""

import json

from renku_data_services.message_queue.models import Event
from renku_data_services.message_queue.orm import EventORM


def test_message_type_getter(app_config) -> None:
    # the messages are stored in the database, where `headers` is a stringifyied dict
    raw_message = json.loads(
        '{"id":"1","headers":"{\\"source\\":\\"renku-data-services\\",\\"type\\":\\"project.created\\",\\"dataContentType\\":\\"application/avro+binary\\",\\"schemaVersion\\":\\"2\\",\\"time\\":1,\\"requestId\\": \\"0\\"}","payload": ""}'  # noqa: E501
    )
    event = Event("search.sync", raw_message)
    event_orm = EventORM.load(event)
    mt = event_orm.get_message_type()
    assert mt == "project.created"
