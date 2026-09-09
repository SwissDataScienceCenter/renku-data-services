"""Constants for data connectors."""

from typing import Final

from renku_data_services.storage.constants import ENVIDAT_V1_PROVIDER, SCICAT_V1_PROVIDER
from renku_data_services.storage.rclone import RCloneOption, RCloneProviderSchema

ALLOWED_GLOBAL_DATA_CONNECTOR_PROVIDERS: Final[list[str]] = ["doi", ENVIDAT_V1_PROVIDER, SCICAT_V1_PROVIDER]

_UNSAFE_SCICAT_COMBINE_PROVIDER = RCloneProviderSchema(
    name="combine",
    description="Combine several remotes into one",
    prefix="combine",
    options=[
        RCloneOption(
            name="upstreams",
            help='Upstreams for combining\n\nThese should be in the form\n\n    dir=remote:path dir2=remote2:path\n\nWhere before the = is specified the root directory and after is the remote to\nput there.\n\nEmbedded spaces can be added using quotes\n\n    "dir=remote:path with space" "dir2=remote2:path with space"\n\n',  # noqa: E501
            provider=None,
            default="",
            value=None,
            examples=None,
            short_opt=None,
            hide=0,
            required=True,
            is_password=False,
            no_prefix=False,
            advanced=False,
            exclusive=False,
            sensitive=False,
            default_str="",
            value_str="",
            type="SpaceSepList",
        ),
        RCloneOption(
            name="description",
            help="Description of the remote.",
            provider=None,
            default="",
            value=None,
            examples=None,
            short_opt=None,
            hide=0,
            required=False,
            is_password=False,
            no_prefix=False,
            advanced=True,
            exclusive=False,
            sensitive=False,
            default_str="",
            value_str="",
            type="string",
        ),
    ],
    command_help=None,
    aliases=None,
    hide=False,
    metadata_info={"System": None, "Help": "Any metadata supported by the underlying remote is read and written."},
)
"""Do not use except for validating inlined s3 configs for Scicat created fully by our own code that we trust."""
