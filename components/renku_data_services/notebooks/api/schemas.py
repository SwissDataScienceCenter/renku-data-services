from datetime import datetime
from marshmallow import (
    Schema,
    fields,
    post_load,
    post_dump,
    validates_schema,
    ValidationError,
    pre_load,
    pre_dump,
    INCLUDE,
    EXCLUDE,
    validate,
)
import collections
import re

from .. import config
from .custom_fields import (
    serverOptionUICpuValue,
    serverOptionUIDiskValue,
    serverOptionUIMemoryValue,
    serverOptionUIUrlValue,
    serverOptionRequestCpuValue,
    serverOptionRequestDiskValue,
    serverOptionRequestMemoryValue,
    serverOptionRequestUrlValue,
    serverOptionRequestLfsAutoFetchValue,
    serverOptionRequestGpuValue,
    LowercaseString,
)
from .classes.server import UserServer
from .classes.s3mount import S3mount
from ..util.file_size import parse_file_size


class LaunchNotebookRequestServerOptions(Schema):
    defaultUrl = serverOptionRequestUrlValue
    cpu_request = serverOptionRequestCpuValue
    mem_request = serverOptionRequestMemoryValue
    disk_request = serverOptionRequestDiskValue
    lfs_auto_fetch = serverOptionRequestLfsAutoFetchValue
    gpu_request = serverOptionRequestGpuValue

    @validates_schema
    def validate_server_options(self, data, **kwargs):
        server_options = config.SERVER_OPTIONS_UI
        for option in data.keys():
            if option not in server_options.keys():
                continue  # presence of option keys are already handled by marshmallow
            if option == "defaultUrl":
                continue  # the defaultUrl field should not be limited to only server options
            if server_options[option]["type"] == "boolean":
                continue  # boolean options are already validated by marshmallow
            if data[option] not in server_options[option]["options"]:
                # check if we allow arbitrary options
                if server_options[option].get("allow_any_value"):
                    value_range = server_options[option].get("value_range")
                    if not value_range:
                        raise RuntimeError("You must specify a value range.")
                    if not _in_range(data[option], value_range):
                        raise ValidationError(
                            f"The value {data[option]} is outside of the range "
                            f"{value_range.get('min')} to {value_range.get('max')}."
                        )
                    continue
                # validate options that can have a set of values against allowed values
                raise ValidationError(
                    f"The value {data[option]} for sever option {option} is not valid, "
                    f"it has to be one of {server_options[option]['options']}"
                )


class LaunchNotebookRequestS3mount(Schema):
    class Meta:
        unknown = EXCLUDE

    access_key = fields.Str(required=False, missing=None)
    secret_key = fields.Str(required=False, missing=None)
    endpoint = fields.Str(required=True, validate=validate.Length(min=1))
    bucket = fields.Str(required=True, validate=validate.Length(min=1))

    @post_load
    def create_s3mount_object(self, data, **kwargs):
        if data["access_key"] == "":
            data.pop("access_key")
        if data["secret_key"] == "":
            data.pop("secret_key")
        s3mount = S3mount(**data, mount_folder="/s3mounts", read_only=True)
        if not s3mount.bucket_exists:
            raise ValidationError(
                f"Cannot find bucket {s3mount.bucket} at endpoint {s3mount.endpoint}. "
                "Please make sure you have provided the correct "
                "credentials, bucket name and endpoint."
            )
        return s3mount


class LaunchNotebookResponseS3mount(LaunchNotebookRequestS3mount):
    class Meta:
        fields = ("endpoint", "bucket")


class LaunchNotebookRequestWithoutS3(Schema):
    """Used to validate the requesting for launching a jupyter server"""

    # namespaces in gitlab are NOT case sensitive
    namespace = LowercaseString(required=True)
    # project names in gitlab are NOT case sensitive
    project = LowercaseString(required=True)
    # branch names in gitlab are case sensitive
    branch = fields.Str(missing="master")
    commit_sha = fields.Str(required=True)
    notebook = fields.Str(missing=None)
    image = fields.Str(missing=None)
    server_options = fields.Nested(
        LaunchNotebookRequestServerOptions(),
        missing=config.SERVER_OPTIONS_DEFAULTS,
        data_key="serverOptions",
        required=False,
    )


class LaunchNotebookRequestWithS3(LaunchNotebookRequestWithoutS3):
    """Used to validate the requesting for launching a jupyter server"""

    s3mounts = fields.List(
        fields.Nested(LaunchNotebookRequestS3mount()),
        required=False,
        missing=[],
    )

    @validates_schema
    def validate_unique_bucket_names(self, data, **kwargs):
        errors = {}
        bucket_names = [i.bucket for i in data["s3mounts"]]
        bucket_names_unique = set(bucket_names)
        if len(bucket_names_unique) < len(bucket_names):
            errors["s3mounts"] = [
                "Found duplicate storage bucket names. "
                "All provided bucket names have to be unique"
            ]
        if errors:
            raise ValidationError(errors)


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


class UserPodResources(
    Schema.from_dict(
        # Memory and CPU resources that should be present in the response to creating a
        # jupyter noteboooks server.
        {
            "cpu": fields.Str(required=True),
            "memory": fields.Str(required=True),
            "storage": fields.Str(required=False),
            "gpu": fields.Str(required=False),
        }
    )
):
    @pre_load
    def resolve_gpu_fieldname(self, in_data, **kwargs):
        if "nvidia.com/gpu" in in_data.keys():
            in_data["gpu"] = in_data.pop("nvidia.com/gpu")
        return in_data


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
    status = fields.Dict()
    url = fields.Str()
    resources = fields.Nested(UserPodResources())
    image = fields.Str()

    @pre_dump
    def format_user_pod_data(self, server, *args, **kwargs):
        """Convert and format a server object into what the API requires."""

        def summarise_pod_conditions(conditions):
            def get_latest_condition(conditions):
                CONDITIONS_ORDER = {
                    "PodScheduled": 1,
                    "Unschedulable": 2,
                    "Initialized": 3,
                    "ContainersReady": 4,
                    "Ready": 5,
                }
                return sorted(
                    conditions,
                    key=lambda c: (
                        c.get("lastTransitionTime"),
                        CONDITIONS_ORDER[c.get("type", "PodScheduled")],
                    ),
                )[-1]

            if not conditions:
                return {"step": None, "message": None, "reason": None}
            else:
                latest = get_latest_condition(conditions)
                return {
                    "step": latest.get("type"),
                    "message": latest.get("message"),
                    "reason": latest.get("reason"),
                }

        def get_status(js):
            """Get the status of the jupyterserver."""
            # Phases: https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#pod-phase
            res = {
                "phase": "Unknown",
                "ready": False,
                "step": None,
                "message": None,
                "reason": None,
            }
            if js is None:
                return res
            container_statuses = (
                js["status"]
                .get("mainPod", {})
                .get("status", {})
                .get("containerStatuses", [])
            )
            res["ready"] = (
                len(container_statuses) > 0
                and all([cs.get("ready") for cs in container_statuses])
                and js["metadata"].get("deletionTimestamp", None) is None
            )
            res["phase"] = (
                js["status"]
                .get("mainPod", {})
                .get("status", {})
                .get("phase", "Unknown")
            )
            conditions = summarise_pod_conditions(
                js["status"].get("mainPod", {}).get("status", {}).get("conditions", [])
            )
            return {**res, **conditions}

        def get_server_resources(server):
            server_options = UserServer._get_server_options_from_js(server.js)
            server_options_keys = server_options.keys()
            # translate the cpu weird numeric string to a normal number
            # ref: https://kubernetes.io/docs/concepts/configuration/
            #   manage-compute-resources-container/#how-pods-with-resource-limits-are-run
            resources = {}
            if (
                "cpu_request" in server_options_keys
                and isinstance(server_options["cpu_request"], str)
                and str.endswith(server_options["cpu_request"], "m")
                and server_options["cpu_request"][:-1].isdigit()
            ):
                resources["cpu"] = str(int(server_options["cpu_request"][:-1]) / 1000)
            elif "cpu_request" in server_options_keys:
                resources["cpu"] = server_options["cpu_request"]
            if "mem_request" in server_options_keys:
                resources["memory"] = server_options["mem_request"]
            if (
                "disk_request" in server_options_keys
                and server_options["disk_request"] is not None
                and server_options["disk_request"] != ""
            ):
                resources["storage"] = server_options["disk_request"]
            if (
                "gpu_request" in server_options_keys
                and int(server_options["gpu_request"]) > 0
            ):
                resources["gpu"] = server_options["gpu_request"]
            return resources

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
            "resources": get_server_resources(server),
            "image": server.image,
        }
        if config.S3_MOUNTS_ENABLED:
            output["s3mounts"] = server.s3mounts
        return output


class LaunchNotebookResponseWithS3(LaunchNotebookResponseWithoutS3):
    """
    The response sent after a successful creation of a jupyter server. Or
    if the user tries to create a server that already exists. Used only for
    serializing the server class into a proper response.
    """

    s3mounts = fields.List(
        fields.Nested(LaunchNotebookResponseS3mount()),
        required=False,
        missing=[],
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
    project = LowercaseString(required=False, default=None)
    commit_sha = fields.String(required=False, default=None)
    # namespaces in gitlab are NOT case sensitive
    namespace = LowercaseString(required=False, default=None)
    # branch names in gitlab are case sensitive
    branch = fields.String(required=False, default=None)


class DefaultResponseSchema(Schema):
    """Schema used for reporting general errors."""

    messages = fields.Dict(keys=fields.Str(), values=fields.Str())


class FailedParsing(Schema):
    """Schema used for reporting errors when parsing of parameters fails."""

    messages = fields.Dict(
        keys=fields.Str(),
        values=fields.Dict(keys=fields.Str, values=fields.List(fields.Str())),
    )


class ServerOptionUIBase(Schema):
    displayName = fields.Str(required=True)
    order = fields.Int(required=True)
    type = fields.String(validate=lambda x: x in ["boolean", "enum"], required=True)


class ServerOptionUICpu(ServerOptionUIBase):
    """The schema used to describe a single option for the server_options endpoint."""

    default = serverOptionUICpuValue
    options = fields.List(
        serverOptionUICpuValue, validate=lambda x: len(x) >= 1, required=True
    )


class ResourceRequestValueRange(Schema):
    """Specifies the valid range of a resource request."""

    type = fields.String(validate=lambda x: x in ["bytes"], required=True)


class DiskRequestValueRange(ResourceRequestValueRange):
    """Specifies the valid disk request range."""

    min = serverOptionUIDiskValue
    max = serverOptionUIDiskValue


class ServerOptionUIDisk(ServerOptionUIBase):
    """The schema used to describe a single option for the server_options endpoint."""

    default = serverOptionUIDiskValue
    options = fields.List(
        serverOptionUIDiskValue, validate=lambda x: len(x) >= 1, required=True
    )
    allow_any_value = fields.Boolean(required=False)
    value_range = fields.Nested(DiskRequestValueRange, required=False)


class ServerOptionUIMemory(ServerOptionUIBase):
    """The schema used to describe a single option for the server_options endpoint."""

    default = serverOptionUIMemoryValue
    options = fields.List(
        serverOptionUIMemoryValue, validate=lambda x: len(x) >= 1, required=True
    )


class ServerOptionUIGpu(ServerOptionUIBase):
    """The schema used to describe a single option for the server_options endpoint."""

    default = fields.Integer(strict=True, validate=lambda x: x >= 0, required=True)
    options = fields.List(
        fields.Integer(strict=True, validate=lambda x: x >= 0),
        validate=lambda x: len(x) >= 1,
        required=True,
    )


class ServerOptionUIString(ServerOptionUIBase):
    """The schema used to describe a single option for the server_options endpoint."""

    default = fields.String(required=True)
    options = fields.List(
        fields.String(), validate=lambda x: len(x) >= 1, required=True
    )


class ServerOptionUIUrl(ServerOptionUIBase):
    """The schema used to describe a single option for the server_options endpoint."""

    default = serverOptionUIUrlValue
    options = fields.List(
        serverOptionUIUrlValue, validate=lambda x: len(x) >= 1, required=True
    )


class ServerOptionUIBool(ServerOptionUIBase):
    """The schema used to describe a single option for the server_options endpoint."""

    default = fields.Bool(required=True)


class ServerOptionsUI(Schema):
    """
    Specifies which options are available to the user in the UI when
    launching a jupyter server. Which fields are required is fully dictated
    by the server options specified in the values.yaml file which are available in
    the config under SERVER_OPTIONS_UI.
    """

    cpu_request = fields.Nested(
        ServerOptionUICpu(), required="cpu_request" in config.SERVER_OPTIONS_UI.keys()
    )
    defaultUrl = fields.Nested(
        ServerOptionUIUrl(), required="defaultUrl" in config.SERVER_OPTIONS_UI.keys()
    )
    gpu_request = fields.Nested(
        ServerOptionUIGpu(), required="gpu_request" in config.SERVER_OPTIONS_UI.keys()
    )
    lfs_auto_fetch = fields.Nested(
        ServerOptionUIBool(),
        required="lfs_auto_fetch" in config.SERVER_OPTIONS_UI.keys(),
    )
    mem_request = fields.Nested(
        ServerOptionUIMemory(),
        required="mem_request" in config.SERVER_OPTIONS_UI.keys(),
    )
    disk_request = fields.Nested(
        ServerOptionUIDisk(), required="disk_request" in config.SERVER_OPTIONS_UI.keys()
    )
    s3mounts = fields.Nested(
        Schema.from_dict({"enabled": fields.Boolean(required=True)})(), required=True
    )


class ServerLogs(Schema):
    """
    The list of k8s logs (one log line per list element)
    for the pod that runs the jupyter server.
    """

    items = fields.List(fields.Str())

    @post_dump
    @post_load
    def remove_item_key(self, data, **kwargs):
        return data.get("items", [])


def _in_range(value, value_range):
    """Check that the value is with the given value range."""

    if value_range.get("type") == "bytes":
        # convert file size notation
        def convert(x):
            return parse_file_size(x)

    else:
        # pass-through
        def convert(x):
            return x

    return (
        convert(value_range.get("min"))
        <= convert(value)
        <= convert(value_range.get("max"))
    )


class AutosavesItem(Schema):
    """Information about an autosave item."""

    commit = fields.String(required=True)
    branch = fields.String(required=True)
    pvs = fields.Bool(required=True)
    date = fields.DateTime(required=True)
    name = fields.String(required=True)

    @pre_dump
    def extract_data(self, autosave, *args, **kwargs):
        return {
            "branch": autosave.root_branch_name,
            "commit": autosave.root_commit_sha,
            "pvs": False,
            "date": autosave.creation_date,
            "name": autosave.name,
        }


class AutosavesList(Schema):
    """List of autosaves branches or PVs."""

    pvsSupport = fields.Bool(required=True)
    autosaves = fields.List(fields.Nested(AutosavesItem), missing=[])


LaunchNotebookResponse = (
    LaunchNotebookResponseWithS3
    if config.S3_MOUNTS_ENABLED
    else LaunchNotebookResponseWithoutS3
)
LaunchNotebookRequest = (
    LaunchNotebookRequestWithS3
    if config.S3_MOUNTS_ENABLED
    else LaunchNotebookRequestWithoutS3
)
