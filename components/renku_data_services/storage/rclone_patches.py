"""Patches to apply to phe rclone storage schema."""

from collections.abc import Callable
from copy import deepcopy
from typing import Any, Final, cast

from renku_data_services import errors

BANNED_STORAGE: Final[set[str]] = {
    "alias",
    "crypt",
    "cache",
    "chunker",
    "combine",
    "compress",
    "hasher",
    "local",
    "memory",
    "union",
}

OAUTH_PROVIDERS: Final[set[str]] = {
    "box",
    "drive",
    "dropbox",
    "gcs",
    "gphotos",
    "hidrive",
    "jottacloud",
    "mailru",
    "onedrive",
    "pcloud",
    "pikpak",
    "premiumizeme",
    "putio",
    "sharefile",
    "yandex",
    "zoho",
}

BANNED_SFTP_OPTIONS: Final[set[str]] = {
    "key_file",  # path to a local file
    "pubkey_file",  # path to a local file
    "known_hosts_file",  # path to a local file
    "ssh",  # arbitrary command to be executed
}


def find_storage(spec: list[dict[str, Any]], prefix: str) -> dict[str, Any]:
    """Find and return the storage schema from the spec.

    This returns the original entry for in-place modification.
    """
    storage = next((s for s in spec if s["Prefix"] == prefix), None)
    if not storage:
        raise errors.ValidationError(message=f"'{prefix}' storage not found in schema.")
    return storage


def __patch_schema_remove_unsafe(spec: list[dict[str, Any]]) -> None:
    """Remove storages that aren't safe to use in the service."""
    indices = [i for i, v in enumerate(spec) if v["Prefix"] in BANNED_STORAGE]
    for i in sorted(indices, reverse=True):
        spec.pop(i)


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
    """Make endpoint required for 'Other' provider."""
    for storage in spec:
        if storage["Prefix"] == "s3":
            for option in storage["Options"]:
                if option["Name"] == "endpoint" and option["Provider"].startswith(
                    "!AWS,ArvanCloud,IBMCOS,IDrive,IONOS,"
                ):
                    option["Required"] = True


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
    existing_endpoint_spec = next(
        o for o in s3["Options"] if o["Name"] == "endpoint" and o["Provider"].startswith("!AWS,")
    )
    existing_endpoint_spec["Provider"] += ",Switch"


def __patch_schema_remove_oauth_propeties(spec: list[dict[str, Any]]) -> None:
    """Removes OAuth2 fields since we can't do an oauth flow in the rclone CSI."""
    for storage in spec:
        if storage["Prefix"] in OAUTH_PROVIDERS:
            options = []
            for option in storage["Options"]:
                if option["Name"] not in ["client_id", "client_secret"]:
                    options.append(option)
            storage["Options"] = options


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


def __patch_schema_remove_banned_sftp_options(spec: list[dict[str, Any]]) -> None:
    """Remove unsafe SFTP options."""
    sftp = find_storage(spec, "sftp")
    options = []
    for option in sftp["Options"]:
        if option["Name"] not in BANNED_SFTP_OPTIONS:
            options.append(option)
    sftp["Options"] = options


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


def __add_custom_doi_s3_provider(name: str, description: str, prefix: str) -> Callable[[list[dict[str, Any]]], None]:
    """This is used to add envidata and scicat as providers.

    However this is not a real provider in Rclone. The data service has to intercept the request
    and convert this provider to the proper S3 configuration where the data can be found.
    """

    def __patch(spec: list[dict[str, Any]]) -> None:
        doi_original = find_storage(spec, "doi")
        doi_new = deepcopy(doi_original)
        doi_new["Description"] = description
        doi_new["Name"] = name
        doi_new["Prefix"] = prefix
        doi_new_options = cast(list[dict[str, Any]], doi_new.get("Options", []))
        provider_ind = next((i for i, opt in enumerate(doi_new_options) if opt.get("Name") == "provider"), None)
        if provider_ind is not None:
            doi_new_options.pop(provider_ind)
        spec.append(doi_new)

    return __patch


def apply_patches(spec: list[dict[str, Any]]) -> None:
    """Apply patches to RClone schema."""
    patches = [
        __patch_schema_remove_unsafe,
        __patch_schema_sensitive,
        __patch_schema_s3_endpoint_required,
        __patch_schema_add_switch_provider,
        __patch_schema_remove_oauth_propeties,
        __patch_polybox_storage,
        __patch_switchdrive_storage,
        # __add_custom_doi_s3_provider("Envidat", "Envidat data provider", ENVIDAT_V1_PROVIDER),
        # TODO: Enable Scicat when it is ready in production
        # __add_custom_doi_s3_provider("SciCat", "SciCat data provider", SCICAT_V1_PROVIDER),
        __patch_schema_remove_banned_sftp_options,
        __patch_schema_add_openbis_type,
    ]

    for patch in patches:
        patch(spec)
