"""Apispec schemas for storage service."""


import json
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, Field, ValidationError
from sanic.log import logger

from renku_data_services import errors


class RCloneValidator:
    """Class for validating RClone configs."""

    def __init__(self) -> None:
        """Initialize with contained schema file."""
        with open(Path(__file__).parent / "rclone_schema.json", "r") as f:
            spec = json.load(f)

        self.providers: dict[str, RCloneProviderSchema] = {}

        for provider_config in spec:
            try:
                provider_schema = RCloneProviderSchema.parse_obj(provider_config)
                self.providers[provider_schema.prefix] = provider_schema
            except ValidationError:
                logger.error("Couldn't load RClone config: %s", provider_config)
                raise

    def validate(self, storage_type: str, configuration: dict[str, Any]):
        """Validates an RClone config."""

        storage_type = storage_type or cast(str, configuration.get("type"))

        provider = self.providers.get(storage_type)

        if provider is None:
            raise errors.ValidationError(message=f"RClone provider '{storage_type}' does not exist.")

        provider.validate_config(configuration)

    def asdict(self) -> list[dict[str, Any]]:
        """Return Schema as dict."""
        return [provider.dict() for provider in self.providers.values()]


class RCloneTriState(BaseModel):
    """Represents a Tristate of true|false|unset."""

    value: bool = Field(alias="Value")
    valid: bool = Field(alias="Valid")


class RCloneExample(BaseModel):
    """Example value for an RClone option."""

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
    examples: list[RCloneExample] | None
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

    def validate_config(self, value, provider: str):
        """Validate an RClone option."""
        if self.sensitive or self.is_password:
            raise errors.ValidationError(message=f"Field '{self.name}' is sensitive and should not be set.")
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
        return [o for o in self.options if o.sensitive or o.is_password]

    def validate_config(self, configuration: dict[str, Any]):
        """Validate an RClone config."""
        keys = set(configuration.keys()) - {"type"}

        provider: str = configuration.get("provider", "")

        missing: list[str] = []

        for required in self.required_options:
            if required.name not in configuration and required.provider == provider:
                missing.append(required.name)

        if missing:
            missing_str = "\n".join(missing)
            raise errors.ValidationError(message=f"The following fields are required but missing:\n{missing_str}")

        for key in keys:
            option: RCloneOption | None = None

            if provider is not None:
                option = next((o for o in self.options if o.name == key and o.provider == provider), None)

            if option is None:
                option = next((o for o in self.options if o.name == key and o.provider == ""), None)

            if option is None:
                logger.info(f"Couldn't find option '{key}' for storage '{self.name}' and provider '{provider}'")
                # some options don't show up in the schema, e.g. for provider 'Other' for S3.
                # We can't actually validate those, so we just continue
                continue

            option.validate_config(configuration[key], provider=provider)
