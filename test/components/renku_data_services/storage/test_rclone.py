"""Tests for the rclone module."""

from typing import Any

import pytest

from renku_data_services.storage.constants import STORAGE_CONFIG
from renku_data_services.storage.rclone import RCloneValidator, convert_rclone_configuration


def test_validate_switch_s3_no_endpoint() -> None:
    """Endpoint has a default value and is not required to specify."""
    validator = RCloneValidator()
    cfg = {"provider": "Switch", "type": "s3"}
    validator.validate(cfg, keep_sensitive=True)


def test_storage_config() -> None:
    spec: list[dict[str, Any]] = RCloneValidator._get_spec()

    # Check that all storage types are covered
    for idx, storage in enumerate(spec):
        pos = idx + 1
        storage_type = storage.get("Prefix")
        assert isinstance(storage_type, str), f"Storage {storage} (#{pos}) has incorrect prefix: {storage_type}."

        config = STORAGE_CONFIG.get(storage_type)
        assert config is not None, f'Storage type "{storage_type}" (#{pos}) is not covered by STORAGE_CONFIG.'

        assert (
            config.options is None or config.allowed
        ), f'Storage type "{storage_type}" (#{pos}) cannot specify options because it is not allowed.'
        if not config.allowed:
            continue

        assert (
            config.options is not None
        ), f'Storage type "{storage_type}" (#{pos}) must specify options because it is allowed.'

        options: list[dict[str, Any]] = storage.get("Options")
        assert isinstance(options, list), f'Storage type "{storage_type}" (#{pos}) has incorrect options.'

        # Check that all options are covered
        all_option_names = [option.get("Name") for option in options]
        for option in options:
            name = option.get("Name")
            assert isinstance(name, str), f'Storage type "{storage_type}" (#{pos}) has incorrect options.'
            assert name != ""

            option_config = config.options.get(name)
            assert option_config is not None, (
                f'Storage type "{storage_type}" (#{pos}) needs to configure option "{name}".'
                f" Full list of options: {all_option_names}."
            )
        # Check that we do not configure unknown options
        for option_name in config.options:
            assert (
                option_name in all_option_names
            ), f'Unknown storage option "{option_name}" in STORAGE_CONFIG"[{storage_type}"].'


def test_storage_config_no_unknown() -> None:
    spec: list[dict[str, Any]] = RCloneValidator._get_spec()
    storage_types = set(storage.get("Prefix") for storage in spec)
    for key in STORAGE_CONFIG:
        assert key in storage_types, f"Unknown storage type {key} in STORAGE_CONFIG."


@pytest.mark.parametrize(
    "input, expected",
    [
        (
            {
                "pass": "<sensitive>",
                "type": "polybox",
                "user": "some-user",
                "provider": "personal",
            },
            {
                "pass": "<sensitive>",
                "type": "webdav",
                "user": "some-user",
                "provider": "",
                "vendor": "owncloud",
                "url": "https://polybox.ethz.ch/remote.php/webdav/",
            },
        ),
        (
            {
                "pass": "some-pwd",
                "type": "polybox",
                "provider": "shared",
                "public_link": "https://polybox.ethz.ch/index.php/s/8NffJ3rFyHaVyyy",
            },
            {
                "pass": "some-pwd",
                "type": "webdav",
                "provider": "",
                "public_link": "https://polybox.ethz.ch/index.php/s/8NffJ3rFyHaVyyy",
                "vendor": "owncloud",
                "url": "https://polybox.ethz.ch/public.php/webdav/",
                "user": "8NffJ3rFyHaVyyy",
            },
        ),
        (
            {
                "pass": "some-pwd",
                "type": "switchDrive",
                "user": "some-user",
                "provider": "personal",
            },
            {
                "pass": "some-pwd",
                "type": "webdav",
                "user": "some-user",
                "provider": "",
                "vendor": "owncloud",
                "url": "https://drive.switch.ch/remote.php/webdav/",
            },
        ),
        (
            {
                "pass": "some-pwd",
                "type": "switchDrive",
                "provider": "shared",
                "public_link": "https://drive.switch.ch/index.php/s/OPSd72zrs5JG666",
            },
            {
                "pass": "some-pwd",
                "type": "webdav",
                "provider": "",
                "public_link": "https://drive.switch.ch/index.php/s/OPSd72zrs5JG666",
                "vendor": "owncloud",
                "url": "https://drive.switch.ch/public.php/webdav/",
                "user": "OPSd72zrs5JG666",
            },
        ),
        (
            {
                "type": "s3",
                "endpoint": "https://s3-zh.os.switch.ch",
                "provider": "Switch",
                "access_key_id": "access-key",
                "secret_access_key": "secret-key",
            },
            {
                "type": "s3",
                "endpoint": "https://s3-zh.os.switch.ch",
                "provider": "Other",
                "access_key_id": "access-key",
                "secret_access_key": "secret-key",
            },
        ),
        (
            {
                "host": "openbis-eln-lims.ethz.ch",
                "type": "openbis",
                "session_token": "token",
            },
            {
                "host": "openbis-eln-lims.ethz.ch",
                "type": "sftp",
                "session_token": "token",
                "port": "2222",
                "user": "?",
                "override.low_level_retries": 1,
            },
        ),
        (
            {"type": "doi", "doi": "10.16904/envidat.790"},
            {"type": "doi", "doi": "10.16904/envidat.790"},
        ),
    ],
)
def test_rclone_convert(input: dict[str, Any], expected: dict[str, Any]) -> None:
    converted = convert_rclone_configuration(input)
    assert converted == expected
