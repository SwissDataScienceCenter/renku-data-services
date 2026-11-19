"""Patches to apply to phe rclone storage schema."""

from copy import deepcopy
from typing import Any, cast

from renku_data_services import errors
from renku_data_services.storage.constants import STORAGE_CONFIG


def find_storage(spec: list[dict[str, Any]], prefix: str) -> dict[str, Any]:
    """Find and return the storage schema from the spec.

    This returns the original entry for in-place modification.
    """
    storage = next((s for s in spec if s["Prefix"] == prefix), None)
    if not storage:
        raise errors.ValidationError(message=f"'{prefix}' storage not found in schema.")
    return storage


def __patch_schema_allow_storage_types_and_options(spec: list[dict[str, Any]]) -> None:
    """Apply the allowed list of storage types and options."""
    spec_copy = spec.copy()
    spec.clear()
    for storage in spec_copy:
        storage_type = cast(str, storage["Prefix"])
        config = STORAGE_CONFIG[storage_type]
        if not config.allowed:
            continue
        options_config = config.options or dict()
        options: list[Any] = []
        for option in storage["Options"]:
            if options_config[option["Name"]]:
                options.append(option)
        storage["Options"] = options
        spec.append(storage)


def __patch_schema_sensitive(spec: list[dict[str, Any]]) -> None:
    """Fix sensitive settings on providers."""
    for storage in spec:
        if storage["Prefix"] == "azureblob":
            for option in storage["Options"]:
                if option["Name"] == "account":
                    option["Sensitive"] = False
        if storage["Prefix"] == "sftp" or storage["Prefix"] == "ftp":
            for option in storage["Options"]:
                if option["Name"] == "host":
                    option["Sensitive"] = False
        if storage["Prefix"] == "webdav":
            for option in storage["Options"]:
                if option["Name"] == "user":
                    option["Sensitive"] = False
                if option["Name"] == "pass":
                    option["Sensitive"] = True


def __patch_schema_s3_endpoint_required(spec: list[dict[str, Any]]) -> None:
    """Make endpoint required for 'Other' and other custom S3 providers.

    RClone has a single, optional 'endpoint' option for S3. We split it in two:
    - the original option, kept optional, for AWS and for the providers for which rclone knows the endpoints
      (i.e. which have endpoint examples).
    - a required copy which applies to all the other providers (e.g. 'Other', 'Minio', 'Ceph') and to
      configurations without a provider.
    """
    s3 = find_storage(spec, "s3")
    endpoint_idx: int | None = None
    endpoint: dict[str, Any] | None = None
    provider_option: dict[str, Any] | None = None
    for idx, option in enumerate(s3["Options"]):
        if endpoint is None and option["Name"] == "endpoint":
            endpoint_idx = idx
            endpoint = option
        elif provider_option is None and option["Name"] == "provider":
            provider_option = option
    if endpoint_idx is None or endpoint is None:
        raise errors.ValidationError(message="'endpoint' option not found in the 's3' storage schema.")
    if provider_option is None:
        raise errors.ValidationError(message="'provider' option not found in the 's3' storage schema.")

    providers_with_endpoint: list[str] = []
    for provider in endpoint["Provider"].split(","):
        if provider:
            providers_with_endpoint.append(provider)

    providers_with_examples: set[str] = set()
    for example in endpoint.get("Examples") or []:
        for provider in (example.get("Provider") or "").split(","):
            if provider:
                providers_with_examples.add(provider)

    all_providers: list[str] = []
    for example in provider_option.get("Examples") or []:
        all_providers.append(example["Value"])

    required_for: set[str] = set()
    for provider in providers_with_endpoint:
        if provider != "AWS" and provider not in providers_with_examples:
            required_for.add(provider)

    optional_for: list[str] = []
    for provider in providers_with_endpoint:
        if provider not in required_for:
            optional_for.append(provider)

    excluded_from_required: list[str] = []
    for provider in all_providers:
        if provider not in required_for:
            excluded_from_required.append(provider)

    endpoint["Provider"] = ",".join(optional_for)

    required_endpoint = deepcopy(endpoint)
    required_endpoint.update(
        {
            "Provider": "!" + ",".join(excluded_from_required),
            "Required": True,
            "Examples": None,
        }
    )
    s3["Options"].insert(endpoint_idx + 1, required_endpoint)


def __patch_schema_add_switch_provider(spec: list[dict[str, Any]]) -> None:
    """Adds a fake provider to help with setting up switch storage."""
    s3 = find_storage(spec, "s3")
    providers = next(o for o in s3["Options"] if o["Name"] == "provider")
    providers["Examples"].append({"Value": "Switch", "Help": "Switch Object Storage", "Provider": ""})
    s3["Options"].append(
        {
            "Name": "endpoint",
            "Help": "Endpoint for Switch S3 API.",
            "Provider": "Switch",
            "Default": "https://s3-zh.os.switch.ch",
            "Value": None,
            "Examples": [
                {"Value": "https://s3-zh.os.switch.ch", "Help": "Cloudian Hyperstore (ZH)", "Provider": ""},
                {"Value": "https://os.zhdk.cloud.switch.ch", "Help": "Ceph Object Gateway (ZH)", "Provider": ""},
                {"Value": "https://os.unil.cloud.switch.ch", "Help": "Ceph Object Gateway (LS)", "Provider": ""},
            ],
            "ShortOpt": "",
            "Hide": 0,
            "Required": True,
            "IsPassword": False,
            "NoPrefix": False,
            "Advanced": False,
            "Exclusive": True,
            "Sensitive": False,
            "DefaultStr": "",
            "ValueStr": "",
            "Type": "string",
        }
    )
    # Exclude Switch from the catch-all (required) endpoint added by __patch_schema_s3_endpoint_required
    existing_endpoint_spec = next(
        o for o in s3["Options"] if o["Name"] == "endpoint" and o.get("Provider", "").startswith("!AWS,")
    )
    existing_endpoint_spec["Provider"] += ",Switch"


def add_webdav_based_storage(
    spec: list[dict[str, Any]],
    prefix: str,
    name: str,
    description: str,
    url_value: str,
    public_link_help: str,
) -> None:
    """Create a modified copy of WebDAV storage and add it to the schema."""
    # Find WebDAV storage schema and create a modified copy
    storage_copy = deepcopy(find_storage(spec, "webdav"))
    storage_copy.update({"Prefix": prefix, "Name": name, "Description": description})

    custom_options = [
        {
            "Name": "provider",
            "Help": "Choose the mode to access the data source.",
            "Provider": "",
            "Default": "",
            "Value": None,
            "Examples": [
                {
                    "Value": "personal",
                    "Help": (
                        "Connect to your personal storage space. "
                        "This data connector cannot be used to share access to a folder."
                    ),
                    "Provider": "",
                },
                {
                    "Value": "shared",
                    "Help": (
                        "Connect a 'public' folder shared with others. "
                        "A 'public' folder may or may not be protected with a password."
                    ),
                    "Provider": "",
                },
            ],
            "Required": True,
            "Type": "string",
            "ShortOpt": "",
            "Hide": 0,
            "IsPassword": False,
            "NoPrefix": False,
            "Advanced": False,
            "Exclusive": True,
            "Sensitive": False,
            "DefaultStr": "",
            "ValueStr": "",
        },
        {
            "Name": "public_link",
            "Help": public_link_help,
            "Provider": "shared",
            "Default": "",
            "Value": None,
            "Examples": None,
            "ShortOpt": "",
            "Hide": 0,
            "Required": True,
            "IsPassword": False,
            "NoPrefix": False,
            "Advanced": False,
            "Exclusive": False,
            "Sensitive": False,
            "DefaultStr": "",
            "ValueStr": "",
            "Type": "string",
        },
    ]
    storage_copy["Options"].extend(custom_options)

    # use provider to indicate if the option is for an personal o shared storage
    for option in storage_copy["Options"]:
        if option["Name"] == "url":
            option.update({"Provider": "personal", "Default": url_value, "Required": False})
        elif option["Name"] in ["bearer_token", "bearer_token_command", "headers", "user"]:
            option["Provider"] = "personal"

    # Remove obsolete options no longer applicable for Polybox or SwitchDrive
    storage_copy["Options"] = [
        o for o in storage_copy["Options"] if o["Name"] not in ["vendor", "nextcloud_chunk_size"]
    ]

    spec.append(storage_copy)


def __patch_polybox_storage(spec: list[dict[str, Any]]) -> None:
    """Add polybox virtual storage that uses webdav."""
    add_webdav_based_storage(
        spec,
        prefix="polybox",
        name="PolyBox",
        description="Polybox",
        url_value="https://polybox.ethz.ch/remote.php/webdav/",
        public_link_help="Shared folder link. E.g., https://polybox.ethz.ch/index.php/s/8NffJ3rFyHaVyyy",
    )


def __patch_switchdrive_storage(spec: list[dict[str, Any]]) -> None:
    """Add switchdrive virtual storage that uses webdav."""
    add_webdav_based_storage(
        spec,
        prefix="switchDrive",
        name="SwitchDrive",
        description="SwitchDrive",
        url_value="https://drive.switch.ch/remote.php/webdav/",
        public_link_help="Shared folder link. E.g., https://drive.switch.ch/index.php/s/OPSd72zrs5JG666",
    )


def __patch_schema_add_openbis_type(spec: list[dict[str, Any]]) -> None:
    """Adds a fake type to help with setting up openBIS storage."""
    spec.append(
        {
            "Name": "openbis",
            "Description": "openBIS",
            "Prefix": "openbis",
            "Options": [
                {
                    "Name": "host",
                    "Help": 'openBIS host to connect to.\n\nE.g. "openbis-eln-lims.ethz.ch".',
                    "Provider": "",
                    "Default": "",
                    "Value": None,
                    "Examples": [
                        {
                            "Value": "openbis-eln-lims.ethz.ch",
                            "Help": "Public openBIS demo instance",
                            "Provider": "",
                        },
                    ],
                    "ShortOpt": "",
                    "Hide": 0,
                    "Required": True,
                    "IsPassword": False,
                    "NoPrefix": False,
                    "Advanced": False,
                    "Exclusive": False,
                    "Sensitive": False,
                    "DefaultStr": "",
                    "ValueStr": "",
                    "Type": "string",
                },
                {
                    "Name": "session_token",
                    "Help": "openBIS session token",
                    "Provider": "",
                    "Default": "",
                    "Value": None,
                    "ShortOpt": "",
                    "Hide": 0,
                    "Required": True,
                    "IsPassword": True,
                    "NoPrefix": False,
                    "Advanced": False,
                    "Exclusive": False,
                    "Sensitive": True,
                    "DefaultStr": "",
                    "ValueStr": "",
                    "Type": "string",
                },
            ],
            "CommandHelp": None,
            "Aliases": None,
            "Hide": False,
            "MetadataInfo": None,
        }
    )


def __patch_schema_combine_remote_default(spec: list[dict[str, Any]]) -> None:
    """Add default value for the "combine" remote.

    Without this if the remote is used then Pydantic schema validation fails.
    """
    for storage in spec:
        if storage["Prefix"] == "combine":
            for option in storage["Options"]:
                if option["Name"].lower() == "upstreams":
                    option["Default"] = ""


def apply_patches(spec: list[dict[str, Any]]) -> None:
    """Apply patches to RClone schema."""
    patches = [
        __patch_schema_allow_storage_types_and_options,
        __patch_schema_sensitive,
        __patch_schema_s3_endpoint_required,
        __patch_schema_add_switch_provider,
        __patch_polybox_storage,
        __patch_switchdrive_storage,
        __patch_schema_add_openbis_type,
        __patch_schema_combine_remote_default,
    ]

    for patch in patches:
        patch(spec)
