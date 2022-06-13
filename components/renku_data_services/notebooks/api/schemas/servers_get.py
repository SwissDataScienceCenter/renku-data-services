import collections
from datetime import datetime
from enum import Enum
from marshmallow import (
    Schema,
    fields,
    EXCLUDE,
    INCLUDE,
    post_load,
    pre_load,
    pre_dump,
    validate,
)
import re

from ... import config
from .custom_fields import LowercaseString
from .cloud_storage import LaunchNotebookResponseS3mount
from ..classes.server import UserServer
from .custom_fields import (
    CpuField,
    GpuField,
    MemoryField,
)


class ServerStatusEnum(Enum):
    """Simple Enum for server status."""

    Running = "running"
    Starting = "starting"
    Stopping = "stopping"
    Failed = "failed"

    @classmethod
    def list(cls):
        return list(map(lambda c: c.value, cls))


class ServerStatus(Schema):
    state = fields.String(
        required=True,
        validate=validate.OneOf(ServerStatusEnum.list()),
    )
    message = fields.String(required=False)


class UserPodAnnotations(
    Schema.from_dict(
        {
            f"{config.RENKU_ANNOTATION_PREFIX}namespace": fields.Str(required=True),
            f"{config.RENKU_ANNOTATION_PREFIX}gitlabProjectId": fields.Str(
                required=False
            ),
            f"{config.RENKU_ANNOTATION_PREFIX}projectName": fields.Str(required=True),
            f"{config.RENKU_ANNOTATION_PREFIX}branch": fields.Str(required=True),
            f"{config.RENKU_ANNOTATION_PREFIX}commit-sha": fields.Str(required=True),
            f"{config.RENKU_ANNOTATION_PREFIX}username": fields.Str(required=False),
            f"{config.RENKU_ANNOTATION_PREFIX}default_image_used": fields.Str(
                required=True
            ),
            f"{config.RENKU_ANNOTATION_PREFIX}repository": fields.Str(required=True),
            f"{config.RENKU_ANNOTATION_PREFIX}git-host": fields.Str(required=False),
            f"{config.JUPYTER_ANNOTATION_PREFIX}servername": fields.Str(required=True),
            f"{config.JUPYTER_ANNOTATION_PREFIX}username": fields.Str(required=True),
        }
    )
):
    """
    Used to validate the annotations of a jupyter user pod
    that are returned to the UI as part of any endpoint that list servers.
    """

    class Meta:
        unknown = INCLUDE

    def get_attribute(self, obj, key, default, *args, **kwargs):
        # in marshmallow, any schema key with a dot in it is converted to nested dictionaries
        # in marshmallow, this overrides that behaviour for dumping (serializing)
        return obj.get(key, default)

    @post_load
    def unnest_keys(self, data, **kwargs):
        # in marshmallow, any schema key with a dot in it is converted to nested dictionaries
        # this overrides that behaviour for loading (deserializing)
        return flatten_dict(data)


class ResourceRequests(Schema):
    cpu = CpuField(required=True)
    memory = MemoryField(required=True)
    storage = MemoryField(required=False)
    gpu = GpuField(required=False)

    @pre_load
    def resolve_gpu_fieldname(self, in_data, **kwargs):
        if "nvidia.com/gpu" in in_data.keys():
            in_data["gpu"] = in_data.pop("nvidia.com/gpu")
        return in_data


class ResourceUsage(Schema):
    cpu = CpuField(required=False)
    memory = MemoryField(required=False)
    storage = MemoryField(required=False)


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

    annotations = fields.Nested(UserPodAnnotations())
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
                128: "The server shut down unexpectedly. Please ensure"
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
                203: "Cannot clone repository: No disk space left on device.",
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
            msg = conditions[0].get("message")
            if not msg:
                return
            re_match = re.match(
                r"^[0-9]+\/[0-9]+ nodes are available: (.+), that the pod didn't tolerate.$",
                msg,
            )
            if not re_match:
                return
            filtered_mgs = re_match.group(1)
            parts = filtered_mgs.split(", ")
            sorted_parts = sorted(
                parts, key=lambda x: int(x.split(" ")[0]), reverse=True
            )
            reason = " ".join(sorted_parts[0].split()[1:])
            return (
                "You session cannot be scheduled due insufficent resources. "
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

        def get_starting_message(container_statuses):
            containers_not_ready = [
                container_status.get("name", "Unknown")
                for container_status in container_statuses
                if not container_status.get("ready", False)
            ]
            if len(containers_not_ready) > 0:
                return f"Containers with non-ready statuses: {', '.join(containers_not_ready)}."
            return None

        def get_status(js):
            """Get the status of the jupyterserver."""
            state = js.get("status", {}).get("state", ServerStatusEnum.Starting.value)
            output = {
                "state": state,
            }
            container_statuses = get_all_container_statuses(js)
            if state == ServerStatusEnum.Failed.value:
                unschedulable_msg = get_unschedulable_message(
                    js.get("status", {}).get("mainPod", {})
                )
                if unschedulable_msg:
                    output["message"] = unschedulable_msg
                else:
                    output["message"] = get_failed_message(
                        get_failed_containers(container_statuses)
                    )
            if state == ServerStatusEnum.Starting:
                output["message"] = get_starting_message(container_statuses)
            return output

        def get_resource_requests(server):
            server_options = UserServer._get_server_options_from_js(server.js)
            server_options_keys = server_options.keys()
            # translate the cpu weird numeric string to a normal number
            # ref: https://kubernetes.io/docs/concepts/configuration/
            #   manage-compute-resources-container/#how-pods-with-resource-limits-are-run
            resources = {}
            if "cpu_request" in server_options_keys:
                resources["cpu"] = server_options["cpu_request"]
            if "mem_request" in server_options_keys:
                resources["memory"] = float(server_options["mem_request"])
            if (
                "disk_request" in server_options_keys
                and server_options["disk_request"] is not None
                and server_options["disk_request"] != ""
            ):
                resources["storage"] = float(server_options["disk_request"])
            if (
                "gpu_request" in server_options_keys
                and int(server_options["gpu_request"]) > 0
            ):
                resources["gpu"] = server_options["gpu_request"]
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
            "annotations": {
                **server.js["metadata"]["annotations"],
                server._renku_annotation_prefix
                + "default_image_used": str(server.using_default_image),
            },
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
        if config.S3_MOUNTS_ENABLED:
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
            if config.S3_MOUNTS_ENABLED
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


def flatten_dict(d, parent_key="", sep="."):
    """
    Convert a nested dictionary into a dictionary that is one level deep.
    Nested dictionaries of any depth have their keys combined by a ".".
    I.e. calling this function on {"A": 1, "B": {"C": {"D": 2}}}
    will result in {"A":1, "B.C.D":2}. Used to address the fact that
    marshamallow will parse schema keys with dots in them as a series
    of nested dictionaries.
    From: https://stackoverflow.com/a/6027615
    """
    items = []
    for k, v in d.items():
        new_key = parent_key + sep + k if parent_key else k
        if isinstance(v, collections.MutableMapping):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


NotebookResponse = (
    LaunchNotebookResponseWithS3
    if config.S3_MOUNTS_ENABLED
    else LaunchNotebookResponseWithoutS3
)
