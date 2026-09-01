"""Apispec schemas for storage service."""

from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import Awaitable, Callable, Generator, MutableMapping
from configparser import ConfigParser
from copy import deepcopy
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, NamedTuple, Union, cast, overload
from urllib.parse import ParseResult, urlparse

from pydantic import BaseModel, Field, PrivateAttr, ValidationError, model_serializer, model_validator

from renku_data_services import errors
from renku_data_services.app_config import logging
from renku_data_services.storage.constants import BLOCKED_OPTIONS, BLOCKED_STORAGES, ENVIDAT_V1_PROVIDER
from renku_data_services.storage.rclone_patches import apply_patches

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from renku_data_services import base_models
    from renku_data_services.notebooks.data_sources import DataSourceRepository


class ConnectionResult(NamedTuple):
    """Result of testing a connection to cloud storage through RClone."""

    success: bool
    error: str


class RCloneValidator:
    """Class for validating RClone configs."""

    def __init__(self) -> None:
        """Initialize with contained schema file."""
        spec = self._get_spec()
        apply_patches(spec)
        self.providers = RCloneValidator._get_providers(spec)

    @staticmethod
    def _is_multi_remote(config: RCloneConfig | dict[str, Any]) -> bool:
        conf = config.config if isinstance(config, RCloneConfig) else config
        return all([isinstance(i, dict) for i in conf.values()])

    def validate(self, configuration: RCloneConfig | dict[str, Any], keep_sensitive: bool = False) -> None:
        """Validates an RClone config."""

        def _transform(conf: RCloneConfig | dict[str, Any]) -> RCloneConfig | dict[str, Any]:
            provider = self.get_provider(conf)
            provider.validate_config(conf, keep_sensitive=keep_sensitive)
            return conf

        self._apply_transform_sync(configuration, _transform)

    async def test_connection(
        self,
        configuration: Union[RCloneConfig, dict[str, Any]],
        source_path: str,
        user: base_models.APIUser | None = None,
        data_source_repo: DataSourceRepository | None = None,
    ) -> ConnectionResult:
        """Tests connecting with an RClone config."""
        if not self._is_multi_remote(configuration):
            try:
                self.get_provider(configuration)
            except errors.ValidationError as e:
                return ConnectionResult(False, str(e))

        # Obscure configuration and transform if needed
        transformed_config = await self.obscure_config(configuration)
        transformed_config = self.inject_default_values(transformed_config)

        transformed_config = convert_rclone_configuration(transformed_config)

        # Handle testing with Renku integrations
        if user is not None and data_source_repo is not None:
            with_oauth2_config = await data_source_repo.handle_configuration_for_test(
                user=user, configuration=transformed_config
            )
            if with_oauth2_config is not None:
                transformed_config = (
                    with_oauth2_config.config if isinstance(with_oauth2_config, RCloneConfig) else with_oauth2_config
                )

        with tempfile.NamedTemporaryFile(mode="w+", delete=False, encoding="utf-8") as f:
            test_conf = configuration if isinstance(configuration, RCloneConfig) else RCloneConfig(config=configuration)
            test_conf.write(PurePosixPath(f.name), name="temp")
            # Handle SFTP retries, see https://github.com/SwissDataScienceCenter/renku-data-services/issues/893
            args = [
                "lsf",
                "--low-level-retries=1",  # Connection tests should fail fast.
                "--retries=1",  # Connection tests should fail fast.
                "--config",
                f.name,
                f"temp:{source_path}",
            ]
            storage_type = cast(str, configuration.get("type"))
            if storage_type == "sftp":
                args.extend(["--low-level-retries", "1"])
            logger.debug(f"Execute: rclone {' '.join(args)}")
            proc = await asyncio.create_subprocess_exec(
                "rclone",
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, error = await proc.communicate()
            success = proc.returncode == 0
        return ConnectionResult(success=success, error=error.decode())

    async def obscure_config(
        self, configuration: Union[RCloneConfig, dict[str, Any]]
    ) -> Union[RCloneConfig, dict[str, Any]]:
        """Obscure secrets in rclone config."""

        async def _transform(configuration: RCloneConfig | dict[str, Any]) -> RCloneConfig | dict[str, Any]:
            provider = self.get_provider(configuration)
            return await provider.obscure_password_options(configuration)

        return await self._apply_transform_async(configuration, _transform)

    def get_provider(self, configuration: Union[RCloneConfig, dict[str, Any]]) -> RCloneProviderSchema:
        """Get a provider for configuration."""
        if self._is_multi_remote(configuration):
            raise NotImplementedError("Cannot get single provider for multi remote configurations")

        storage_type = cast(str | None, configuration.get("type"))

        if storage_type is None:
            raise errors.ValidationError(
                message="Expected a `type` field in the RClone configuration, but didn't find it."
            )
        if storage_type in BLOCKED_STORAGES:
            raise errors.ValidationError(message=f"Storage '{storage_type}' is not supported.")

        provider = self.providers.get(storage_type)

        if provider is None:
            raise errors.ValidationError(message=f"RClone provider '{storage_type}' does not exist.")
        return provider

    def asdict(self) -> list[dict[str, Any]]:
        """Return Schema as dict."""
        return [provider.model_dump(exclude_none=True, by_alias=True) for provider in self.providers.values()]

    def get_private_fields(
        self, configuration: Union[RCloneConfig, dict[str, Any]]
    ) -> Generator[RCloneOption, None, None]:
        """Get private field descriptions for storage."""
        if self._is_multi_remote(configuration):
            raise NotImplementedError("Cannot handle private fields for multi remote configurations")
        provider = self.get_provider(configuration)
        return provider.get_private_fields(configuration)

    @overload
    def inject_default_values(self, config: RCloneConfig) -> RCloneConfig: ...
    @overload
    def inject_default_values(self, config: dict[str, Any]) -> dict[str, Any]: ...
    def inject_default_values(self, config: Union[RCloneConfig, dict[str, Any]]) -> Union[RCloneConfig, dict[str, Any]]:
        """Adds default values for required options that are not provided in the config."""
        is_multi_remote = self._is_multi_remote(config)
        if is_multi_remote:
            remotes = config.config if isinstance(config, RCloneConfig) else config
            remotes = cast(dict[str, dict[str, Any]], remotes)
        else:
            remotes = {"main": config.config if isinstance(config, RCloneConfig) else config}

        output: dict[str, Any] = {}
        for id, remote in remotes.items():
            ioutput: dict[str, Any] = deepcopy(remote)
            provider = self.get_provider(ioutput)
            cfg_provider: str | None = ioutput.get("provider")

            for opt in provider.options:
                if not opt.required or not opt.default or opt.name in ioutput or not opt.matches_provider(cfg_provider):
                    continue

                match opt.default:
                    case RCloneTriState() as ts:
                        def_val: Any = ts.value
                    case v:
                        def_val = v

                ioutput.update({opt.name: def_val})

            if is_multi_remote:
                output = ioutput
                break
            else:
                output[id] = ioutput

        return RCloneConfig(config=output) if isinstance(config, RCloneConfig) else output

    @staticmethod
    def _get_spec() -> Any:
        """Get the rclone spec file."""
        with open(Path(__file__).parent / "rclone_schema.autogenerated.json") as f:
            spec = json.load(f)
        return spec

    @staticmethod
    def _get_providers(spec: Any) -> dict[str, RCloneProviderSchema]:
        """Read the spec and parse it into a dict of Providers."""
        providers: dict[str, RCloneProviderSchema] = {}

        for provider_config in spec:
            try:
                provider_schema = RCloneProviderSchema.model_validate(provider_config)
                providers[provider_schema.prefix] = provider_schema
            except ValidationError:
                logger.error("Couldn't load RClone config: %s", provider_config)
                raise

        return providers

    async def _apply_transform_async(
        self,
        configuration: RCloneConfig | dict[str, Any],
        transformation: Callable[[RCloneConfig | dict[str, Any]], Awaitable[RCloneConfig | dict[str, Any]]],
    ) -> RCloneConfig | dict[str, Any]:
        is_multi_remote = self._is_multi_remote(configuration)
        config = configuration.config if isinstance(configuration, RCloneConfig) else configuration
        output = deepcopy(config)
        if not is_multi_remote:
            return await transformation(output)
        output = cast(dict[str, dict[str, Any] | RCloneConfig], output)
        for id, remote in output.items():
            output[id] = await transformation(remote)
        return output

    def _apply_transform_sync(
        self,
        configuration: RCloneConfig | dict[str, Any],
        transformation: Callable[[RCloneConfig | dict[str, Any]], RCloneConfig | dict[str, Any]],
    ) -> RCloneConfig | dict[str, Any]:
        is_multi_remote = self._is_multi_remote(configuration)
        config = configuration.config if isinstance(configuration, RCloneConfig) else configuration
        output = deepcopy(config)
        if not is_multi_remote:
            return transformation(output)
        output = cast(dict[str, dict[str, Any] | RCloneConfig], output)
        for id, remote in output.items():
            output[id] = transformation(remote)
        return output


@lru_cache(maxsize=1)
def get_rclone_validator() -> RCloneValidator:
    """Returns a shared, cached instance of RCloneValidator."""
    return RCloneValidator()


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
            valid_values = ", ".join([v.value for v in self.examples])
            raise errors.ValidationError(
                message=f"Value '{value}' is not valid for field {self.name}. Valid values are: {valid_values}"
            )
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
        return [o for o in self.options if o.required and not o.default]

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

    def check_unsafe_option(self, name: str) -> None:
        """Check that the option is safe."""
        blocked = BLOCKED_OPTIONS.get(self.prefix.lower(), None)
        if blocked is None:
            return None
        if name in blocked:
            raise errors.ValidationError(message=f"The {name} option is not allowed.")
        return None

    def validate_config(self, configuration: Union[RCloneConfig, dict[str, Any]], keep_sensitive: bool = False) -> None:
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
            self.check_unsafe_option(key)

            value = configuration[key]

            option: RCloneOption | None = self.get_option_for_provider(key, provider)

            if option is None:
                logger.info(f"Couldn't find option '{key}' for storage '{self.name}' and provider '{provider}'")
                # some options don't show up in the schema, e.g. for provider 'Other' for S3.
                # We can't actually validate those, so we just continue
                continue

            configuration[key] = option.validate_config(value, provider=provider, keep_sensitive=keep_sensitive)

    def remove_sensitive_options_from_config(self, configuration: Union[RCloneConfig, dict[str, Any]]) -> None:
        """Remove sensitive options from configuration."""
        for sensitive in self.sensitive_options:
            if sensitive.name in configuration:
                del configuration[sensitive.name]

    async def obscure_password_options(
        self, configuration: Union[RCloneConfig, dict[str, Any]]
    ) -> Union[RCloneConfig, dict[str, Any]]:
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
        self, configuration: Union[RCloneConfig, dict[str, Any]]
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


def _transform_polybox_switchdriver_config(configuration: Union[RCloneConfig, dict[str, Any]]) -> None:
    """Transform the configuration for public access."""
    storage_type = configuration.get("type")

    # Only process Polybox or SwitchDrive configurations
    if storage_type not in {"polybox", "switchDrive"}:
        return None

    configuration["type"] = "webdav"

    # NOTE: Without the vendor field mounting storage and editing files results in the modification
    # time for touched files to be temporarily set to `1999-09-04` which causes the text
    # editor to complain that the file has changed and whether it should overwrite new changes.
    configuration["vendor"] = "owncloud"

    provider = configuration.get("provider")

    if provider in ["personal", "shared"]:
        configuration["provider"] = ""

    if provider == "personal":
        configuration["url"] = configuration.get("url") or (
            "https://polybox.ethz.ch/remote.php/webdav/"
            if storage_type == "polybox"
            else "https://drive.switch.ch/remote.php/webdav/"
        )
        return None

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


def _transform_envidat_config(configuration: RCloneConfig | dict[str, Any]) -> None:
    """Used to convert the configuration for Envidat into a real configuration."""
    storage_type = configuration.get("type")
    if storage_type is None:
        return None
    if storage_type != ENVIDAT_V1_PROVIDER:
        return None
    configuration["type"] = "doi"


def _transform_switch_config(configuration: RCloneConfig | dict[str, Any]) -> None:
    """Converts a Renku specific Switch S3 config into a regular RClone config."""
    if configuration.get("type") != "s3" or configuration.get("provider") != "Switch":
        return
    # Switch is a fake provider we add for users, we need to replace it since rclone itself
    # doesn't know it
    configuration["provider"] = "Other"


def _transform_openbis_config(configuration: RCloneConfig | dict[str, Any]) -> None:
    if configuration.get("type") != "openbis":
        return None
    configuration["type"] = "sftp"
    configuration["port"] = "2222"
    configuration["user"] = "?"


def _transform_sftp_retries(configuration: RCloneConfig | dict[str, Any]) -> None:
    if configuration.get("type") == "sftp" or configuration.get("type") == "openbis":
        # Do not allow retries for sftp
        # Reference: https://rclone.org/docs/#globalconfig
        configuration["override.low_level_retries"] = 1


@overload
def convert_rclone_configuration(configuration: RCloneConfig) -> RCloneConfig: ...
@overload
def convert_rclone_configuration(configuration: dict[str, Any]) -> dict[str, Any]: ...
def convert_rclone_configuration(configuration: dict[str, Any] | RCloneConfig) -> dict[str, Any] | RCloneConfig:
    """Converts a Renku-specific RClone configuration into a regular RClone configuration."""
    new_config = deepcopy(configuration.config if isinstance(configuration, RCloneConfig) else configuration)
    _transform_switch_config(new_config)
    _transform_openbis_config(new_config)
    _transform_polybox_switchdriver_config(new_config)
    _transform_envidat_config(new_config)
    _transform_sftp_retries(new_config)
    output = RCloneConfig(config=new_config) if isinstance(configuration, RCloneConfig) else new_config
    return output


class RCloneConfig(BaseModel, MutableMapping):
    """Class for RClone configuration that is valid."""

    config: dict[str, Any] = Field(exclude=True)

    _validator: RCloneValidator = PrivateAttr(default_factory=get_rclone_validator)

    @model_validator(mode="after")
    def check_rclone_schema(self) -> RCloneConfig:
        """Validate that the reclone config is valid."""
        self._validator.validate(self.config)
        return self

    @model_serializer
    def serialize_model(self) -> dict[str, Any]:
        """Serialize model by returning contained dict."""
        return self.config

    def __len__(self) -> int:
        return len(self.config)

    def __getitem__(self, k: str) -> Any:
        return self.config[k]

    def __setitem__(self, key: str, value: Any) -> None:
        self.config[key] = value
        self._validator.validate(self.config)

    def __delitem__(self, key: str) -> None:
        del self.config[key]
        self._validator.validate(self.config)

    def __iter__(self) -> Generator[str, None, None]:  # type: ignore[override]
        """Iterate method.

        Needed for pydantic to properly serialize the object.
        """
        yield from self.config.keys()

    def _stringify_bool(value: Any) -> str:
        """Converts booleans to a rclone compliant values."""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def write(self, path: PurePosixPath, name: str = "temp") -> None:
        """Write the configuration as an rclone ini-style config file.

        If the config contains multiple remotes,
        the name given name is assigned to the remote that combines all remotes.
        The name of the remote that combine all others is expected to be "combine" or "union".
        If the config containss a single remote the name you provide is assigned to the remote.
        When the config has multiple remotes it is assumed that the keys of teh dictionary are the remote names.
        """

        def _stringify_bool(value: Any) -> str:
            """Converts booleans to a rclone compliant values."""
            if isinstance(value, bool):
                return "true" if value else "false"
            return str(value)

        multiple_remotes = all([isinstance(i, dict) for i in self.config.values()])

        if not multiple_remotes and not name:
            raise errors.ValidationError(
                message="Cannot write rclone configuration that has a single remote and no name."
            )

        to_write = cast(dict[str, dict[str, Any]], self.config) if multiple_remotes else {name: self.config}

        parser = ConfigParser(interpolation=None)

        for section_name, section in to_write.items():
            if multiple_remotes and section_name in ["union", "combine"]:
                section_name = name
            parser.add_section(section_name)
            for k, v in section.items():
                parser.set(section_name, k, _stringify_bool(v))

        with open(path, "w") as f:
            parser.write(f)


def parse_storage_url(storage_url: str) -> tuple[RCloneConfig, str]:
    """Get Cloud Storage/rclone config from a storage URL.

    Example:
        Supported URLs are:
        - s3://s3.<region>.amazonaws.com/<bucket>/<path>
        - s3://<bucket>.s3.<region>.amazonaws.com/<path>
        - s3://bucket/
        - http(s)://<endpoint>/<bucket>/<path>
        - (azure|az)://<account>.dfs.core.windows.net/<container>/<path>
        - (azure|az)://<account>.blob.core.windows.net/<container>/<path>
        - (azure|az)://<container>/<path>
    """

    def from_s3_url(storage_url: ParseResult) -> tuple[RCloneConfig, str]:
        """Get Cloud storage from an S3 URL.

        Example:
            Supported URLs are:
            - s3://s3.<region>.amazonaws.com/<bucket>/<path>
            - s3://<bucket>.s3.<region>.amazonaws.com/<path>
            - s3://bucket/
            - https://<endpoint>/<bucket>/<path>
        """

        if storage_url.hostname is None:
            raise errors.ValidationError(message="Storage URL must contain a host")

        configuration = {"type": "s3"}
        source_path = storage_url.path.lstrip("/")

        if storage_url.scheme == "s3":
            configuration["provider"] = "AWS"
            match storage_url.hostname.split(".", 4):
                case ["s3", region, "amazonaws", "com"]:
                    configuration["region"] = region
                case [bucket, "s3", region, "amazonaws", "com"]:
                    configuration["region"] = region
                    source_path = f"{bucket}{storage_url.path}"
                case _:
                    # URL like 's3://giab/' where the bucket is the
                    source_path = f"{storage_url.hostname}/{source_path}" if source_path else storage_url.hostname
        else:
            configuration["endpoint"] = storage_url.netloc

        return RCloneConfig(config=configuration), source_path

    def from_azure_url(storage_url: ParseResult) -> tuple[RCloneConfig, str]:
        """Get Cloud storage from an Azure URL.

        Example:
            Supported URLs are:
            - (azure|az)://<account>.dfs.core.windows.net/<container>/<path>
            - (azure|az)://<account>.blob.core.windows.net/<container>/<path>
            - (azure|az)://<container>/<path>
        """
        if storage_url.hostname is None:
            raise errors.ValidationError(message="Storage URL must contain a host")

        configuration = {"type": "azureblob"}
        source_path = storage_url.path.lstrip("/")

        match storage_url.hostname.split(".", 5):
            case [account, "dfs", "core", "windows", "net"] | [account, "blob", "core", "windows", "net"]:
                configuration["account"] = account
            case _:
                if "." in storage_url.hostname:
                    raise errors.ValidationError(message="Host cannot contain dots unless it's a core.windows.net URL")

                source_path = f"{storage_url.hostname}{storage_url.path}"
        return RCloneConfig(config=configuration), source_path

    def _from_ambiguous_url(storage_url: ParseResult) -> tuple[RCloneConfig, str]:
        """Get cloud storage from an ambiguous storage url."""
        if storage_url.hostname is None:
            raise errors.ValidationError(message="Storage URL must contain a host")

        if storage_url.hostname.endswith(".windows.net"):
            return from_azure_url(storage_url)

        # default to S3 for unknown URLs, since these are way more common
        return from_s3_url(storage_url)

    parsed_url = urlparse(storage_url)

    if parsed_url.scheme is None:
        raise errors.ValidationError(message="Couldn't parse scheme of 'storage_url'")

    match parsed_url.scheme:
        case "s3":
            return from_s3_url(parsed_url)
        case "azure" | "az":
            return from_azure_url(parsed_url)
        case "http" | "https":
            return _from_ambiguous_url(parsed_url)
        case _:
            raise errors.ValidationError(message=f"Scheme '{parsed_url.scheme}' is not supported.")
