"""Apispec schemas for storage service."""


import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generator, Union, cast

from pydantic import BaseModel, Field, ValidationError
from sanic.log import logger

from renku_data_services import errors

if TYPE_CHECKING:
    from renku_data_services.storage_models import RCloneConfig


class RCloneValidator:
    """Class for validating RClone configs."""

    def __init__(self) -> None:
        """Initialize with contained schema file."""
        with open(Path(__file__).parent / "rclone_schema.autogenerated.json", "r") as f:
            spec = json.load(f)

        self.apply_patches(spec)

        self.providers: dict[str, RCloneProviderSchema] = {}

        for provider_config in spec:
            try:
                provider_schema = RCloneProviderSchema.model_validate(provider_config)
                self.providers[provider_schema.prefix] = provider_schema
            except ValidationError:
                logger.error("Couldn't load RClone config: %s", provider_config)
                raise

    @staticmethod
    def __patch_schema_azure_account_sensitive(spec: list[dict[str, Any]]) -> None:
        """Make account name not sensitive."""
        for storage in spec:
            if storage["Prefix"] == "azureblob":
                for option in storage["Options"]:
                    if option["Name"] == "account":
                        option["Sensitive"] = False

    @staticmethod
    def __patch_schema_s3_endpoint_required(spec: list[dict[str, Any]]) -> None:
        """Make endpoint required for 'Other' provider."""
        for storage in spec:
            if storage["Prefix"] == "s3":
                for option in storage["Options"]:
                    if option["Name"] == "endpoint" and option["Provider"].startswith(
                        "!AWS,ArvanCloud,IBMCOS,IDrive,IONOS,"
                    ):
                        option["Required"] = True

    def apply_patches(self, spec: list[dict[str, Any]]) -> None:
        """Apply patches to RClone schema."""
        patches = [
            getattr(self, m)
            for m in dir(self)
            if callable(getattr(self, m)) and m.startswith("_RCloneValidator__patch_schema_")
        ]

        for patch in patches:
            patch(spec)

    def validate(
        self, configuration: Union["RCloneConfig", dict[str, Any]], private: bool = False, keep_sensitive: bool = False
    ):
        """Validates an RClone config."""
        provider = self.get_provider(configuration)

        provider.validate_config(configuration, private=private, keep_sensitive=keep_sensitive)

    def remove_sensitive_options_from_config(self, configuration: Union["RCloneConfig", dict[str, Any]]):
        """Remove sensitive fields from a config, e.g. when turning a private storage public."""

        provider = self.get_provider(configuration)

        provider.remove_sensitive_options_from_config(configuration)

    def get_provider(self, configuration: Union["RCloneConfig", dict[str, Any]]) -> "RCloneProviderSchema":
        """Get a provider for configuration."""

        storage_type = cast(str, configuration.get("type"))

        if storage_type is None:
            raise errors.ValidationError(
                message="Expected a `type` field in the RClone configuration, but didn't find it."
            )

        provider = self.providers.get(storage_type)

        if provider is None:
            raise errors.ValidationError(message=f"RClone provider '{storage_type}' does not exist.")
        return provider

    def asdict(self) -> list[dict[str, Any]]:
        """Return Schema as dict."""
        return [provider.model_dump() for provider in self.providers.values()]

    def get_private_fields(self, configuration: Union["RCloneConfig", dict[str, Any]]):
        """Get private field descriptions for storage."""
        provider = self.get_provider(configuration)
        return provider.get_private_fields(configuration)


class RCloneTriState(BaseModel):
    """Represents a Tristate of true|false|unset."""

    value: bool = Field(alias="Value")
    valid: bool = Field(alias="Valid")


class RCloneExample(BaseModel):
    """Example value for an RClone option.

    RClone calls this example, but it really is an enum. If `exclusive` is `true`, only values specified here can
    be used, potentially further filtered by `provider` if a provider is selected.
    """

    value: str = Field(alias="Value")
    help: str = Field(alias="Help")
    provider: str = Field(alias="Provider")


class RCloneOption(BaseModel):
    """Option for an RClone provider."""

    name: str = Field(alias="Name")
    help: str = Field(alias="Help")
    provider: str = Field(alias="Provider")
    default: str | int | bool | list[str] | RCloneTriState | None = Field(alias="Default")
    value: str | int | bool | RCloneTriState | None = Field(alias="Value")
    examples: list[RCloneExample] | None = Field(default=None)
    short_opt: str = Field(alias="ShortOpt")
    hide: int = Field(alias="Hide")
    required: bool = Field(alias="Required")
    is_password: bool = Field(alias="IsPassword")
    no_prefix: bool = Field(alias="NoPrefix")
    advanced: bool = Field(alias="Advanced")
    exclusive: bool = Field(alias="Exclusive")
    sensitive: bool = Field(alias="Sensitive")
    default_str: str = Field(alias="DefaultStr")
    value_str: str = Field(alias="ValueStr")
    type: str = Field(alias="Type")

    @property
    def is_sensitive(self):
        """Whether this options is sensitive (e.g. credentials) or not."""
        return self.sensitive or self.is_password

    def matches_provider(self, provider: str | None) -> bool:
        """Check if this option applies for a provider.

        Note:
            The field can contain multiple providers separated by comma and can be preceded by a '!'
            which flips the matching logic.
        """
        if self.provider is None or self.provider == "":
            return True

        match_type = True
        provider_check = [self.provider]
        if provider_check[0].startswith("!"):
            match_type = False
            provider_check = [provider_check[0].lstrip("!")]
        if "," in provider_check[0]:
            provider_check = provider_check[0].split(",")

        return (provider in provider_check) == match_type

    def validate_config(self, value, provider: str | None, keep_sensitive: bool = False):
        """Validate an RClone option."""
        if not keep_sensitive and self.is_sensitive:
            return "<sensitive>"
        match self.type:
            case "int" | "Duration" | "SizeSuffix" | "MultiEncoder":
                if not isinstance(value, int):
                    raise errors.ValidationError(message=f"Value '{value}' for field '{self.name}' is not of type int")
            case "bool":
                if not isinstance(value, bool):
                    raise errors.ValidationError(message=f"Value '{value}' for field '{self.name}' is not of type bool")
            case "Tristate":
                if not isinstance(value, dict):
                    raise errors.ValidationError(
                        message=f"Value '{value}' for field '{self.name}' is not of type Dict(Tristate)"
                    )
            case "string" | _:
                if not isinstance(value, str):
                    raise errors.ValidationError(
                        message=f"Value '{value}' for field '{self.name}' is not of type string"
                    )

        if self.examples and self.exclusive:
            if not any(e.value == str(value) and e.provider == provider for e in self.examples):
                raise errors.ValidationError(message=f"Value '{value}' is not valid for field {self.name}")
        return value


class RCloneProviderSchema(BaseModel):
    """Schema for an RClone provider."""

    name: str = Field(alias="Name")
    description: str = Field(alias="Description")
    prefix: str = Field(alias="Prefix")
    options: list[RCloneOption] = Field(alias="Options")
    command_help: list[dict[str, Any]] | None = Field(alias="CommandHelp")
    aliases: list[str] | None = Field(alias="Aliases")
    hide: bool = Field(alias="Hide")
    metadata_info: dict[str, Any] | None = Field(alias="MetadataInfo")

    @property
    def required_options(self) -> list[RCloneOption]:
        """Returns all required options for this provider."""
        return [o for o in self.options if o.required]

    @property
    def sensitive_options(self) -> list[RCloneOption]:
        """Returns all sensitive options for this provider."""
        return [o for o in self.options if o.is_sensitive]

    def get_option_for_provider(self, name: str, provider: str | None) -> RCloneOption | None:
        """Get an RClone option matching a provider."""
        for option in self.options:
            if option.name != name:
                continue
            if option.matches_provider(provider):
                return option

        return None

    def validate_config(
        self, configuration: Union["RCloneConfig", dict[str, Any]], private: bool = False, keep_sensitive: bool = False
    ):
        """Validate an RClone config."""
        keys = set(configuration.keys()) - {"type"}
        provider: str | None = configuration.get("provider")  # type: ignore

        missing: list[str] = []

        # remove None values to allow for deletion
        for key in list(keys):
            if configuration[key] is None:
                del configuration[key]
                keys.remove(key)

        for required in self.required_options:
            if required.name not in configuration and required.matches_provider(provider):
                missing.append(required.name)

        if missing:
            missing_str = "\n".join(missing)
            raise errors.ValidationError(message=f"The following fields are required but missing:\n{missing_str}")

        if not private:
            for sensitive in self.sensitive_options:
                if sensitive.name in configuration:
                    raise errors.ValidationError(
                        message=f"Setting value for field '{sensitive.name}', which is sensitive, is not allowed for"
                        " public storage"
                    )

        for key in keys:
            value = configuration[key]

            if isinstance(value, str):
                # validate strings for Postgresql compatibility
                if "\x00" in value:
                    raise errors.ValidationError(message=f"Null byte found in value '{value}' for key '{key}'")

            option: RCloneOption | None = self.get_option_for_provider(key, provider)

            if option is None:
                logger.info(f"Couldn't find option '{key}' for storage '{self.name}' and provider '{provider}'")
                # some options don't show up in the schema, e.g. for provider 'Other' for S3.
                # We can't actually validate those, so we just continue
                continue

            configuration[key] = option.validate_config(value, provider=provider, keep_sensitive=keep_sensitive)

    def remove_sensitive_options_from_config(self, configuration: Union["RCloneConfig", dict[str, Any]]):
        """Remove sensitive options from configuration."""
        for sensitive in self.sensitive_options:
            if sensitive.name in configuration:
                del configuration[sensitive.name]

    def get_private_fields(
        self, configuration: Union["RCloneConfig", dict[str, Any]]
    ) -> Generator[RCloneOption, None, None]:
        """Get private field descriptions for storage."""
        provider: str | None = configuration.get("provider")  # type: ignore

        for option in self.options:
            if not option.is_sensitive:
                continue
            if option.advanced:
                continue
            if not option.matches_provider(provider):
                continue
            yield option
