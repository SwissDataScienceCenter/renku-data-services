"""Apispec schemas for storage service."""

import asyncio
import json
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple, Union, cast

from pydantic import BaseModel, Field, ValidationError
from sanic.log import logger

from renku_data_services import errors
from renku_data_services.storage.rclone_patches import BANNED_STORAGE, apply_patches

if TYPE_CHECKING:
    from renku_data_services.storage.models import RCloneConfig


class ConnectionResult(NamedTuple):
    """Result of testing a connection to cloud storage through RClone."""

    success: bool
    error: str


class RCloneValidator:
    """Class for validating RClone configs."""

    def __init__(self) -> None:
        """Initialize with contained schema file."""
        with open(Path(__file__).parent / "rclone_schema.autogenerated.json") as f:
            spec = json.load(f)

        apply_patches(spec)

        self.providers: dict[str, RCloneProviderSchema] = {}

        for provider_config in spec:
            try:
                provider_schema = RCloneProviderSchema.model_validate(provider_config)
                self.providers[provider_schema.prefix] = provider_schema
            except ValidationError:
                logger.error("Couldn't load RClone config: %s", provider_config)
                raise

    def validate(self, configuration: Union["RCloneConfig", dict[str, Any]], keep_sensitive: bool = False) -> None:
        """Validates an RClone config."""
        provider = self.get_provider(configuration)

        provider.validate_config(configuration, keep_sensitive=keep_sensitive)

    async def test_connection(
        self, configuration: Union["RCloneConfig", dict[str, Any]], source_path: str
    ) -> ConnectionResult:
        """Tests connecting with an RClone config."""
        try:
            self.get_provider(configuration)
        except errors.ValidationError as e:
            return ConnectionResult(False, str(e))

        # Obscure configuration and transform if needed
        obscured_config = await self.obscure_config(configuration)
        transformed_config = self.transform_polybox_switchdriver_config(obscured_config)

        with tempfile.NamedTemporaryFile(mode="w+", delete=False, encoding="utf-8") as f:
            config = "\n".join(f"{k}={v}" for k, v in transformed_config.items())
            f.write(f"[temp]\n{config}")
            f.close()
            proc = await asyncio.create_subprocess_exec(
                "rclone",
                "lsf",
                "--config",
                f.name,
                f"temp:{source_path}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, error = await proc.communicate()
            success = proc.returncode == 0
        return ConnectionResult(success=success, error=error.decode())

    async def obscure_config(
        self, configuration: Union["RCloneConfig", dict[str, Any]]
    ) -> Union["RCloneConfig", dict[str, Any]]:
        """Obscure secrets in rclone config."""
        provider = self.get_provider(configuration)
        result = await provider.obscure_password_options(configuration)
        return result

    def remove_sensitive_options_from_config(self, configuration: Union["RCloneConfig", dict[str, Any]]) -> None:
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
        if storage_type in BANNED_STORAGE:
            raise errors.ValidationError(message=f"Storage '{storage_type}' is not supported.")

        provider = self.providers.get(storage_type)

        if provider is None:
            raise errors.ValidationError(message=f"RClone provider '{storage_type}' does not exist.")
        return provider

    def asdict(self) -> list[dict[str, Any]]:
        """Return Schema as dict."""
        return [provider.model_dump(exclude_none=True, by_alias=True) for provider in self.providers.values()]

    def get_private_fields(
        self, configuration: Union["RCloneConfig", dict[str, Any]]
    ) -> Generator["RCloneOption", None, None]:
        """Get private field descriptions for storage."""
        provider = self.get_provider(configuration)
        return provider.get_private_fields(configuration)

    @staticmethod
    def transform_polybox_switchdriver_config(
        configuration: Union["RCloneConfig", dict[str, Any]],
    ) -> Union["RCloneConfig", dict[str, Any]]:
        """Transform the configuration for public access."""
        storage_type = configuration.get("type")

        # Only process Polybox or SwitchDrive configurations
        if storage_type not in {"polybox", "switchDrive"}:
            return configuration

        configuration["type"] = "webdav"

        provider = configuration.get("provider")

        if provider == "personal":
            configuration["url"] = configuration.get("url") or (
                "https://polybox.ethz.ch/remote.php/webdav/"
                if storage_type == "polybox"
                else "https://drive.switch.ch/remote.php/webdav/"
            )
            return configuration

        ## Set url and username when is a shared configuration
        configuration["url"] = (
            "https://polybox.ethz.ch/public.php/webdav/"
            if storage_type == "polybox"
            else "https://drive.switch.ch/public.php/webdav/"
        )
        public_link = configuration.get("public_link")

        if not public_link:
            raise ValueError("Missing 'public_link' for public access configuration.")

        # Extract the user from the public link
        configuration["user"] = public_link.split("/")[-1]

        return configuration


class RCloneTriState(BaseModel):
    """Represents a Tristate of true|false|unset."""

    value: bool = Field(validation_alias="Value")
    valid: bool = Field(validation_alias="Valid")


class RCloneExample(BaseModel):
    """Example value for an RClone option.

    RClone calls this example, but it really is an enum. If `exclusive` is `true`, only values specified here can
    be used, potentially further filtered by `provider` if a provider is selected.
    """

    value: str = Field(validation_alias="Value")
    help: str = Field(validation_alias="Help")
    provider: str | None = Field(validation_alias="Provider", default=None)


class RCloneOption(BaseModel):
    """Option for an RClone provider."""

    name: str = Field(validation_alias="Name")
    help: str = Field(validation_alias="Help")
    provider: str | None = Field(validation_alias="Provider", default=None)
    default: str | int | bool | list[str] | RCloneTriState | None = Field(validation_alias="Default")
    value: str | int | bool | RCloneTriState | None = Field(validation_alias="Value")
    examples: list[RCloneExample] | None = Field(default=None, validation_alias="Examples")
    short_opt: str | None = Field(validation_alias="ShortOpt", default=None)
    hide: int = Field(validation_alias="Hide")
    required: bool = Field(validation_alias="Required")
    is_password: bool = Field(validation_alias="IsPassword", serialization_alias="ispassword")
    no_prefix: bool = Field(validation_alias="NoPrefix")
    advanced: bool = Field(validation_alias="Advanced")
    exclusive: bool = Field(validation_alias="Exclusive")
    sensitive: bool = Field(validation_alias="Sensitive")
    default_str: str = Field(validation_alias="DefaultStr")
    value_str: str = Field(validation_alias="ValueStr")
    type: str = Field(validation_alias="Type")

    @property
    def is_sensitive(self) -> bool:
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

    def validate_config(
        self, value: Any, provider: str | None, keep_sensitive: bool = False
    ) -> int | bool | dict | str:
        """Validate an RClone option.

        Sensitive values are replaced with '<sensitive>' placeholders that clients are expected to handle.
        The placeholders indicate that a value should be there without storing the value.
        """
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

        if (
            self.examples
            and self.exclusive
            and not any(e.value == str(value) and (not e.provider or e.provider == provider) for e in self.examples)
        ):
            raise errors.ValidationError(message=f"Value '{value}' is not valid for field {self.name}")
        return cast(int | bool | dict | str, value)


class RCloneProviderSchema(BaseModel):
    """Schema for an RClone provider."""

    name: str = Field(validation_alias="Name")
    description: str = Field(validation_alias="Description")
    prefix: str = Field(validation_alias="Prefix")
    options: list[RCloneOption] = Field(validation_alias="Options")
    command_help: list[dict[str, Any]] | None = Field(validation_alias="CommandHelp")
    aliases: list[str] | None = Field(validation_alias="Aliases")
    hide: bool = Field(validation_alias="Hide")
    metadata_info: dict[str, Any] | None = Field(validation_alias="MetadataInfo")

    @property
    def required_options(self) -> list[RCloneOption]:
        """Returns all required options for this provider."""
        return [o for o in self.options if o.required]

    @property
    def sensitive_options(self) -> list[RCloneOption]:
        """Returns all sensitive options for this provider."""
        return [o for o in self.options if o.is_sensitive]

    @property
    def password_options(self) -> list[RCloneOption]:
        """Returns all password options for this provider."""
        return [o for o in self.options if o.is_password]

    def get_option_for_provider(self, name: str, provider: str | None) -> RCloneOption | None:
        """Get an RClone option matching a provider."""
        for option in self.options:
            if option.name != name:
                continue
            if option.matches_provider(provider):
                return option

        return None

    def validate_config(
        self, configuration: Union["RCloneConfig", dict[str, Any]], keep_sensitive: bool = False
    ) -> None:
        """Validate an RClone config."""
        keys = set(configuration.keys()) - {"type"}
        provider: str | None = configuration.get("provider")

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

        for key in keys:
            value = configuration[key]

            option: RCloneOption | None = self.get_option_for_provider(key, provider)

            if option is None:
                logger.info(f"Couldn't find option '{key}' for storage '{self.name}' and provider '{provider}'")
                # some options don't show up in the schema, e.g. for provider 'Other' for S3.
                # We can't actually validate those, so we just continue
                continue

            configuration[key] = option.validate_config(value, provider=provider, keep_sensitive=keep_sensitive)

    def remove_sensitive_options_from_config(self, configuration: Union["RCloneConfig", dict[str, Any]]) -> None:
        """Remove sensitive options from configuration."""
        for sensitive in self.sensitive_options:
            if sensitive.name in configuration:
                del configuration[sensitive.name]

    async def obscure_password_options(
        self, configuration: Union["RCloneConfig", dict[str, Any]]
    ) -> Union["RCloneConfig", dict[str, Any]]:
        """Obscure all password options."""
        for passwd in self.password_options:
            if val := configuration.get(passwd.name):
                proc = await asyncio.create_subprocess_exec(
                    "rclone",
                    "obscure",
                    val,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                result, error = await proc.communicate()
                success = proc.returncode == 0
                if not success:
                    raise errors.ConfigurationError(
                        message=f"Couldn't obscure password value for field '{passwd.name}'"
                    )
                configuration[passwd.name] = result.decode().strip()
        return configuration

    def get_private_fields(
        self, configuration: Union["RCloneConfig", dict[str, Any]]
    ) -> Generator[RCloneOption, None, None]:
        """Get private field descriptions for storage."""
        provider: str | None = configuration.get("provider")

        for option in self.options:
            if not option.is_sensitive:
                continue
            if not option.matches_provider(provider):
                continue
            if option.name not in configuration:
                continue
            yield option
