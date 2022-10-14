import re
from collections import OrderedDict
from datetime import datetime
from enum import Enum

from marshmallow import (
    EXCLUDE,
    Schema,
    fields,
    pre_dump,
    pre_load,
    validate,
)

from ...config import config
from ..classes.server import UserServer
from .cloud_storage import LaunchNotebookResponseS3mount
from .custom_fields import ByteSizeField, CpuField, GpuField, LowercaseString


class ServerStatusEnum(Enum):
    """Simple Enum for server status."""

    Running = "running"
    Starting = "starting"
    Stopping = "stopping"
    Failed = "failed"

    @classmethod
    def list(cls):
        return list(map(lambda c: c.value, cls))


class StepStatusEnum(Enum):
    ready: str = "ready"  # An init job completely done or container fully running
    waiting: str = "waiting"  # Waiting to start
    executing: str = "executing"  # Running but not complete or fully ready
    failed: str = "failed"

    @classmethod
    def list(cls):
        return list(map(lambda c: c.value, cls))


class ServerStatusDetail(Schema):
    step = fields.String(required=True)
    status = fields.String(
        required=True,
        validate=validate.OneOf(StepStatusEnum.list()),
    )


class ServerStatus(Schema):
    state = fields.String(
        required=True,
        validate=validate.OneOf(ServerStatusEnum.list()),
    )
    message = fields.String(required=False)
    details = fields.List(fields.Nested(ServerStatusDetail), required=True)
    totalNumContainers = fields.Integer(
        required=True,
        validate=validate.Range(min=0, min_inclusive=True),
    )
    readyNumContainers = fields.Integer(
        required=True,
        validate=validate.Range(min=0, min_inclusive=True),
    )


class ResourceRequests(Schema):
    cpu = CpuField(required=True)
    memory = ByteSizeField(required=True)
    storage = ByteSizeField(required=False)
    gpu = GpuField(required=False)

    @pre_load
    def resolve_gpu_fieldname(self, in_data, **kwargs):
        if "nvidia.com/gpu" in in_data.keys():
            in_data["gpu"] = in_data.pop("nvidia.com/gpu")
        return in_data


class ResourceUsage(Schema):
    cpu = CpuField(required=False)
    memory = ByteSizeField(required=False)
    storage = ByteSizeField(required=False)


class UserPodResources(Schema):
    requests = fields.Nested(ResourceRequests(), required=True)
    usage = fields.Nested(ResourceUsage(), required=False)


class LaunchNotebookResponseWithoutS3(Schema):
    """
    The response sent after a successful creation of a jupyter server. Or
    if the user tries to create a server that already exists. Used only for
    serializing the server class into a proper response.
    """

    class Meta:
        # passing unknown params does not error, but the params are ignored
        unknown = EXCLUDE

    annotations = fields.Nested(config.session_get_endpoint_annotations.schema())
    name = fields.Str()
    state = fields.Dict()
    started = fields.DateTime(format="iso", allow_none=True)
    status = fields.Nested(ServerStatus())
    url = fields.Str()
    resources = fields.Nested(UserPodResources())
    image = fields.Str()

    @pre_dump
    def format_user_pod_data(self, server, *args, **kwargs):
        """Convert and format a server object into what the API requires."""

        def get_failed_container_exit_code(container_status):
            """Assumes the container is truly failed and extracts the exit code."""
            last_states = list(container_status.get("lastState", {}).values())
            last_state = last_states[-1] if len(last_states) > 0 else {}
            exit_code = last_state.get("exitCode", "unknown")
            return exit_code

        def get_user_correctable_message(exit_code):
            """Maps failure codes to messages that can help the user resolve a failed session."""
            default_server_error_message = (
                "The server shut down unexpectedly. Please ensure "
                "that your Dockerfile is correct and up-to-date."
            )
            exit_code_msg_xref = {
                # INFO: the command is found but cannot be invoked
                125: "The command to start the server was invoked but "
                "it did not complete successfully. Please make sure your Dockerfile "
                "is correct and up-to-date.",
                # INFO: the command is found but cannot be invoked
                126: "The command to start the server cannot be invoked. "
                "Please make sure your Dockerfile is correct and up-to-date.",
                # INFO: the command cannot be found at all
                127: "The image does not contain the required command to start the server. "
                "Please make sure your Dockerfile is correct and up-to-date.",
                # INFO: the container exited with an invalid exit code
                # happens when container fully runs out of storage
                128: "The server shut down unexpectedly. Please ensure "
                "that your Dockerfile is correct and up-to-date. "
                "In some cases this can be the result of low disk space, "
                "please restart your server with more storage.",
                # INFO: the container aborted itself using the abort() function.
                134: default_server_error_message,
                # INFO: receiving SIGKILL - eviction or oomkilled should trigger this
                137: "The server was terminated by the cluster. Potentially because of "
                "consuming too much resources. Please restart your server and request "
                "more memory and storage.",
                # INFO: segmentation fault
                139: default_server_error_message,
                # INFO: receiving SIGTERM
                143: default_server_error_message,
                200: "Cannot clone repository: Unhandled git error.",
                201: "Cannot clone repository: Git remote server is unavailable. Try again later.",
                202: "Cannot clone repository: "
                "Autosave branch name is in an unexpected format and cannot be processed.",
                203: "Cannot clone repository: No disk space left on device, "
                "please stop this session and start a new one with more storage.",
                204: "Cannot clone repository: Requested branch doesn't exist on remote.",
                205: "Cannot clone repository: Error fetching submodules.",
            }
            return exit_code_msg_xref.get(exit_code, default_server_error_message)

        def get_failed_message(failed_containers):
            """The failed message tries to extract a meaningful error info from the containers."""
            num_failed_containers = len(failed_containers)
            if num_failed_containers == 0:
                return None
            for container in failed_containers:
                exit_code = get_failed_container_exit_code(container)
                container_name = container.get("name", "Unknown")
                if container_name == "git-clone" or container_name == "jupyter-server":
                    # INFO: The git-clone init container ran out of disk space
                    # or the server container failed
                    user_correctable_message = get_user_correctable_message(exit_code)
                    return user_correctable_message
            return (
                f"There are failures in {num_failed_containers} auxiliary "
                "server containers. Please restart your session as this may be "
                "an intermittent problem. If issues persist contact your "
                "administrator or the Renku team."
            )

        def get_unschedulable_message(pod) -> str:
            phase = pod.get("status", {}).get("phase")
            conditions = pod.get("status", {}).get("conditions", [])
            sorted_conditions = sorted(
                conditions,
                key=lambda x: datetime.fromisoformat(
                    x["lastTransitionTime"].rstrip("Z")
                ),
                reverse=True,
            )
            if not (
                phase == "Pending"
                and len(sorted_conditions) >= 1
                and sorted_conditions[0].get("reason") == "Unschedulable"
            ):
                return
            msg = sorted_conditions[0].get("message")
            if not msg:
                return
            initial_test = re.match(r"^[0-9]+\/[0-9]+ nodes are available", msg)
            msg_parts = re.split(r",\ (?=[0-9])|:\ (?=[0-9])", msg.rstrip("."))
            if not initial_test or len(msg_parts) < 2:
                # INFO: The unschedulable message cannot be parsed, so return all of it.
                return msg
            msg_parts = msg_parts[1:]
            try:
                sorted_parts = sorted(
                    msg_parts, key=lambda x: int(x.split(" ")[0]), reverse=True
                )
            except (ValueError, KeyError):
                return msg
            reason = sorted_parts[0].lstrip("1234567890 ")
            return (
                "Your session cannot be scheduled due to insufficent resources. "
                f"The most likely reason is: '{reason}'. You may wait for resources "
                "to free up or you can adjust the specific resource and restart your session."
            )

        def get_all_container_statuses(js):
            return js["status"].get("mainPod", {}).get("status", {}).get(
                "containerStatuses", []
            ) + js["status"].get("mainPod", {}).get("status", {}).get(
                "initContainerStatuses", []
            )

        def get_failed_containers(container_statuses):
            failed_containers = [
                container_status
                for container_status in container_statuses
                if (
                    container_status.get("state", {})
                    .get("terminated", {})
                    .get("exitCode", 0)
                    != 0
                    or container_status.get("lastState", {})
                    .get("terminated", {})
                    .get("exitCode", 0)
                    != 0
                )
            ]
            return failed_containers

        def get_starting_message(step_summary):
            steps_not_ready = [
                step["step"].lower()
                for step in step_summary
                if step["status"] != StepStatusEnum.ready.value
            ]
            if len(steps_not_ready) > 0:
                return f"Steps with non-ready statuses: {', '.join(steps_not_ready)}."
            return None

        def get_status_breakdown(js):
            init_container_summary = (
                js.get("status", {}).get("containerStates", {}).get("init", {})
            )
            container_summary = (
                js.get("status", {}).get("containerStates", {}).get("regular", {})
            )
            output = []
            init_container_name_desc_xref = OrderedDict(
                [
                    ("init-certificates", "Initialization"),
                    ("download-image", "Downloading server image"),
                    ("git-clone", "Cloning and configuring the repository"),
                ]
            )
            container_name_desc_xref = OrderedDict(
                [
                    ("git-proxy", "Git credentials services"),
                    ("oauth2-proxy", "Authentication and proxying services"),
                    ("passthrough-proxy", "Proxying services"),
                    ("git-sidecar", "Auxiliary session services"),
                    ("jupyter-server", "Starting session"),
                ]
            )
            current_state = js.get("status", {}).get("state")
            if (
                current_state is None
                or current_state == ServerStatusEnum.Starting.value
            ):
                # NOTE: This means that the server is starting and the statuses are not populated
                # yet, therefore in this case we will use defaults and set all statuses to waiting
                if len(init_container_summary) == 0:
                    init_container_summary = {
                        container_name: StepStatusEnum.waiting.value
                        for container_name in config.sessions.init_containers
                    }
                if len(container_summary) == 0:
                    annotations = js.get("metadata", {}).get("annotations", {})
                    prefix = (
                        config.session_get_endpoint_annotations.renku_annotation_prefix
                    )
                    is_user_anonymous = (
                        annotations.get(f"{prefix}userId", "").startswith("anon-")
                        and annotations.get(f"{prefix}username", "").startswith("anon-")
                        and js.get("metadata", {}).get("name", "").startswith("anon-")
                    )
                    container_summary = {
                        container_name: StepStatusEnum.waiting.value
                        for container_name in (
                            config.sessions.containers.anonymous
                            if is_user_anonymous
                            else config.sessions.containers.registered
                        )
                    }
            for (container, desc) in init_container_name_desc_xref.items():
                if container in init_container_summary:
                    output.append(
                        {
                            "step": desc,
                            "status": init_container_summary[container],
                        }
                    )
            for (container, desc) in container_name_desc_xref.items():
                if container in container_summary:
                    output.append(
                        {
                            "step": desc,
                            "status": container_summary[container],
                        }
                    )
            return output

        def get_status(js):
            """Get the status of the jupyterserver."""
            state = js.get("status", {}).get("state", ServerStatusEnum.Starting.value)
            output = {
                "state": state,
            }
            container_statuses = get_all_container_statuses(js)
            if state == ServerStatusEnum.Failed.value:
                failed_container_statuses = get_failed_containers(container_statuses)
                unschedulable_msg = get_unschedulable_message(
                    js.get("status", {}).get("mainPod", {})
                )
                if unschedulable_msg:
                    output["message"] = unschedulable_msg
                else:
                    output["message"] = get_failed_message(failed_container_statuses)
            output["details"] = get_status_breakdown(js)
            if state == ServerStatusEnum.Starting.value:
                output["message"] = get_starting_message(output["details"])
            output["totalNumContainers"] = len(output["details"])
            output["readyNumContainers"] = len(
                [
                    step
                    for step in output["details"]
                    if step["status"] in [StepStatusEnum.ready.value]
                ]
            )
            return output

        def get_resource_requests(server):
            server_options = UserServer._get_server_options_from_js(server.js)
            server_options_keys = server_options.keys()
            # translate the cpu weird numeric string to a normal number
            # ref: https://kubernetes.io/docs/concepts/configuration/
            #   manage-compute-resources-container/#how-pods-with-resource-limits-are-run
            resources = {}
            if "cpu_request" in server_options_keys:
                resources["cpu"] = CpuField().deserialize(server_options["cpu_request"])
            if "mem_request" in server_options_keys:
                resources["memory"] = ByteSizeField().deserialize(
                    server_options["mem_request"]
                )
            if (
                "disk_request" in server_options_keys
                and server_options["disk_request"] is not None
                and server_options["disk_request"] != ""
            ):
                resources["storage"] = ByteSizeField().deserialize(
                    server_options["disk_request"]
                )
            if "gpu_request" in server_options_keys:
                gpu_request = GpuField().deserialize(server_options["gpu_request"])
                if gpu_request > 0:
                    resources["gpu"] = gpu_request
            return resources

        def get_resource_usage(server):
            usage = (
                server.js.get("status", {}).get("mainPod", {}).get("resourceUsage", {})
            )
            formatted_output = {}
            if "cpuMillicores" in usage:
                formatted_output["cpu"] = usage["cpuMillicores"] / 1000
            if "memoryBytes" in usage:
                formatted_output["memory"] = usage["memoryBytes"]
            if "disk" in usage and "usedBytes" in usage["disk"]:
                formatted_output["storage"] = usage["disk"]["usedBytes"]
            return formatted_output

        output = {
            "annotations": config.session_get_endpoint_annotations.sanitize_dict(
                {
                    **server.js["metadata"]["annotations"],
                    config.session_get_endpoint_annotations.renku_annotation_prefix
                    + "default_image_used": str(server.using_default_image),
                }
            ),
            "name": server.server_name,
            "state": {"pod_name": server.js["status"].get("mainPod", {}).get("name")},
            "started": datetime.fromisoformat(
                re.sub(r"Z$", "+00:00", server.js["metadata"]["creationTimestamp"])
            ),
            "status": get_status(server.js),
            "url": server.server_url,
            "resources": {
                "requests": get_resource_requests(server),
                "usage": get_resource_usage(server),
            },
            "image": server.image,
        }
        if config.s3_mounts_enabled:
            output["cloudstorage"] = server.cloudstorage
        return output


class LaunchNotebookResponseWithS3(LaunchNotebookResponseWithoutS3):
    """
    The response sent after a successful creation of a jupyter server. Or
    if the user tries to create a server that already exists. Used only for
    serializing the server class into a proper response.
    """

    cloudstorage = fields.List(
        fields.Nested(LaunchNotebookResponseS3mount()),
        required=False,
        dump_default=[],
    )


class ServersGetResponse(Schema):
    """The response for listing all servers that are active or launched by a user."""

    servers = fields.Dict(
        keys=fields.Str(),
        values=fields.Nested(
            LaunchNotebookResponseWithS3()
            if config.s3_mounts_enabled
            else LaunchNotebookResponseWithoutS3()
        ),
    )


class ServersGetRequest(Schema):
    class Meta:
        # passing unknown params does not error, but the params are ignored
        unknown = EXCLUDE

    # project names in gitlab are NOT case sensitive
    project = LowercaseString(required=False)
    commit_sha = fields.String(required=False)
    # namespaces in gitlab are NOT case sensitive
    namespace = LowercaseString(required=False)
    # branch names in gitlab are case sensitive
    branch = fields.String(required=False)


NotebookResponse = (
    LaunchNotebookResponseWithS3
    if config.s3_mounts_enabled
    else LaunchNotebookResponseWithoutS3
)
