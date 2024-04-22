from typing import TypeAlias, Union
from renku_data_services.message_queue.avro_models.io.renku.events.v2.group_added import GroupAdded
from renku_data_services.message_queue.avro_models.io.renku.events.v2.member_role import MemberRole
from renku_data_services.message_queue.avro_models.io.renku.events.v2.group_member_removed import GroupMemberRemoved
from renku_data_services.message_queue.avro_models.io.renku.events.v2.group_member_updated import GroupMemberUpdated
from renku_data_services.message_queue.avro_models.io.renku.events.v2.group_removed import GroupRemoved
from renku_data_services.message_queue.avro_models.io.renku.events.v2.group_updated import GroupUpdated
from renku_data_services.message_queue.avro_models.io.renku.events.v2.group_member_added import GroupMemberAdded
from renku_data_services.message_queue.avro_models.io.renku.events.v2.visibility import Visibility
from renku_data_services.message_queue.avro_models.io.renku.events.v2.project_member_added import ProjectMemberAdded
from renku_data_services.message_queue.avro_models.io.renku.events.v2.project_member_removed import ProjectMemberRemoved
from renku_data_services.message_queue.avro_models.io.renku.events.v2.project_member_updated import ProjectMemberUpdated
from renku_data_services.message_queue.avro_models.io.renku.events.v2.project_removed import ProjectRemoved
from renku_data_services.message_queue.avro_models.io.renku.events.v2.project_updated import ProjectUpdated
from renku_data_services.message_queue.avro_models.io.renku.events.v2.user_added import UserAdded
from renku_data_services.message_queue.avro_models.io.renku.events.v2.user_removed import UserRemoved
from renku_data_services.message_queue.avro_models.io.renku.events.v2.user_updated import UserUpdated
from renku_data_services.message_queue.avro_models.io.renku.events.v2.project_created import ProjectCreated
project_member_changed = type[Union[ProjectMemberAdded, ProjectMemberUpdated, ProjectMemberRemoved]]
