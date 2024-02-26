"""Message queue implementation for redis streams."""

import copy
from dataclasses import dataclass
from datetime import datetime

from ulid import ULID

from renku_data_services.message_queue.avro_models.io.renku.events.v1.header import Header
from renku_data_services.message_queue.avro_models.io.renku.events.v1.project_created import ProjectCreated
from renku_data_services.message_queue.avro_models.io.renku.events.v1.visibility import Visibility as MsgVisibility
from renku_data_services.message_queue.config import RedisConfig
from renku_data_services.message_queue.interface import IMessageQueue
from renku_data_services.project.apispec import Visibility
from renku_data_services.project.orm import ProjectRepositoryORM


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

    async def project_created(
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
    ):
        """Event for when a new project is created."""
        headers = self._create_header("project.created")
        headers_json = copy.deepcopy(headers)
        headers_json.dataContentType = "application/avro+json"
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
            "payload": body.serialize(),
        }

        await self.config.redis_connection.xadd("project.created", message)
        message: dict[bytes | memoryview | str | int | float, bytes | memoryview | str | int | float] = {
            "id": message_id,
            "headers": headers_json.serialize_json(),
            "payload": body.serialize_json(),
        }
        await self.config.redis_connection.xadd("project.created", message)
