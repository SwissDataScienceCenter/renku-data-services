"""Constants for data connectors."""

from typing import Final

from renku_data_services.storage.constants import ENVIDAT_V1_PROVIDER, SCICAT_V1_PROVIDER
from renku_data_services.storage.rclone import RCloneProviderSchema

ALLOWED_GLOBAL_DATA_CONNECTOR_PROVIDERS: Final[list[str]] = ["doi", ENVIDAT_V1_PROVIDER, SCICAT_V1_PROVIDER]

_UNSAFE_SCICAT_COMBINE_PROVIDER = RCloneProviderSchema.model_validate(
    dict(
        Name="combine",
        Description="Combine several remotes into one",
        Prefix="combine",
        Options=[
            dict(
                Name="upstreams",
                Help='Upstreams for combining\n\nThese should be in the form\n\n    dir=remote:path dir2=remote2:path\n\nWhere before the = is specified the root directory and after is the remote to\nput there.\n\nEmbedded spaces can be added using quotes\n\n    "dir=remote:path with space" "dir2=remote2:path with space"\n\n',  # noqa: E501
                Provider=None,
                Default="",
                Value=None,
                Examples=None,
                ShortOpt=None,
                Hide=0,
                Required=True,
                IsPassword=False,
                NoPrefix=False,
                Advanced=False,
                Exclusive=False,
                Sensitive=False,
                DefaultStr="",
                ValueStr="",
                Type="SpaceSepList",
            ),
            dict(
                Name="description",
                Help="Description of the remote.",
                Provider=None,
                Default="",
                Value=None,
                Examples=None,
                ShortOpt=None,
                Hide=0,
                Required=False,
                IsPassword=False,
                NoPrefix=False,
                Advanced=True,
                Exclusive=False,
                Sensitive=False,
                DefaultStr="",
                ValueStr="",
                Type="string",
            ),
        ],
        CommandHelp=None,
        Aliases=None,
        Hide=False,
        MetadataInfo={"System": None, "Help": "Any metadata supported by the underlying remote is read and written."},
    )
)
"""Do not use except for validating inlined s3 configs for Scicat created fully by our own code that we trust."""
