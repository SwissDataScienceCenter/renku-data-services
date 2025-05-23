"""Logging configuration.

This is a central place for configuring the logging library, so that
all log message have the same format. The intention is to use it like
described in the manual of python logging:

Define a module based logger like this:

``` python
import renku_data_services.app_config.logging as logging

logger = logging.getLogger(__name__)
```

In order to make sure, our loggers are always below
`renku_data_services`, it is recommended to use the `getLogger`
function of this module. It will only delegate to the logging library
making sure the logger name is prefixed correctly.

Additionally, there is a `LoggerAdapter` to amend log messages with a
request id. This can be used to uniformly add this information to each
log message. The logger needs to be wrapped into a the
`LoggerApapter`:

``` python
logger = logging.with_request_id(logger, "request-42")
```

Before accessing loggers, run the `configure_logging()` method to
configure loggers appropriately.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from logging import Logger, LoggerAdapter
from typing import Any, Final, cast, final

from renku_data_services.errors.errors import ConfigurationError

__app_root_logger: Final[str] = "renku_data_services"


def getLogger(name: str) -> Logger:
    """Return a logger with the name prefixed with our app name, if not already done."""
    if name.startswith(__app_root_logger + "."):
        return logging.getLogger(name)
    else:
        return logging.getLogger(f"{__app_root_logger}.{name}")


def with_request_id(logger: Logger, request_id: str) -> LoggerAdapter:
    """Amend `logger` adding `request_id` to every log message."""
    return _RequestIdAdapter.create(logger, request_id)


class _RenkuLogFormatter(logging.Formatter):
    """Custom formatter.

    It is used to encapsulate the formatting options and to use
    datetime instead of struct_time.
    """

    def __init__(self) -> None:
        super().__init__(
            fmt=(
                "%(asctime)s [%(levelname)s] %(process)d/%(threadName)s "
                "%(name)s (%(filename)s:%(lineno)d) - %(message)s"
            ),
            datefmt="%Y-%m-%dT%H:%M:%S.%f%z",
        )

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        """Overriden to format the time string for %(asctime) interpolator."""
        ct = datetime.fromtimestamp(record.created)
        return ct.strftime(cast(str, self.datefmt))


class _RenkuJsonFormatter(_RenkuLogFormatter):
    """Formatter to produce json log messages."""

    fields: Final[set[str]] = set(
        [
            "name",
            "levelno",
            "pathname",
            "module",
            "filename",
            "lineno",
        ]
    )
    default_fields: Final[set[str]] = set(fields).union(set(["exc_info", "stack_info", "asctime", "message", "msg"]))

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record."""
        super().format(record)
        return json.dumps(self._to_dict(record))

    def _to_dict(self, record: logging.LogRecord) -> dict:
        base = {field: getattr(record, field, None) for field in self.fields}
        extra = {key: value for key, value in record.__dict__.items() if key not in self.default_fields}
        info = {}
        if record.exc_info:
            info["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            info["stack_info"] = self.formatStack(record.stack_info)
        return {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": record.getMessage(),
            **base,
            **info,
            **extra,
        }


class LogFormatStyle(StrEnum):
    """Supported log formats."""

    plain = "plain"
    json = "json"

    def to_formatter(self) -> logging.Formatter:
        """Return the formatter instance corresponding to this format style."""
        match self:
            case LogFormatStyle.plain:
                return _RenkuLogFormatter()
            case LogFormatStyle.json:
                return _RenkuJsonFormatter()

    @classmethod
    def from_env(cls, prefix: str = "") -> LogFormatStyle:
        """Read the format style from env var `LOG_FORMAT`."""
        str_value = os.environ.get(f"{prefix}LOG_FORMAT_STYLE", "plain").lower()
        match str_value:
            case "plain":
                return LogFormatStyle.plain
            case "json":
                return LogFormatStyle.json
            case _:
                return LogFormatStyle.plain


@final
class _Utils:
    @classmethod
    def get_numeric_level(cls, level_name: str) -> int:
        ln = logging.getLevelNamesMapping().get(level_name.upper())
        if ln is None:
            raise ConfigurationError(message=f"Logging config problem: level name '{level_name}' is not known.")
        return ln

    @classmethod
    def _logger_list_from_env(cls, level: int) -> list[str]:
        level_name = logging._levelToName.get(level)
        if level_name is None:
            return []

        key = f"{level_name.upper()}_LOGGING"
        value = os.environ.get(key, "").strip()
        if value == "":
            return []

        return [n.strip() for n in value.split(",")]

    @classmethod
    def logger_levels_from_env(cls) -> dict[int, list[str]]:
        config = {}
        for level in list(logging._levelToName.keys()):
            logger_names = cls._logger_list_from_env(level)
            if logger_names != []:
                config.update({level: logger_names})

        return config

    @classmethod
    def get_all_loggers(cls) -> list[logging.Logger]:
        """Return the current snapshot of all loggers, including the root logger."""
        all_loggers = [log for log in logging.Logger.manager.loggerDict.values() if isinstance(log, logging.Logger)]
        all_loggers.append(logging.root)
        return all_loggers


@dataclass
class Config:
    """Configuration for logging."""

    format_style: LogFormatStyle = LogFormatStyle.plain
    root_level: int = logging.WARNING
    app_level: int = logging.INFO
    override_levels: dict[int, list[str]] = field(default_factory=dict)

    @classmethod
    def from_env(cls, prefix: str = "") -> Config:
        """Return a config obtained from environment variables."""
        root_level = _Utils.get_numeric_level(os.environ.get(f"{prefix}LOG_ROOT_LEVEL", "WARNING"))
        app_level = _Utils.get_numeric_level(os.environ.get(f"{prefix}LOG_APP_LEVEL", "INFO"))
        format_style = LogFormatStyle.from_env(prefix)
        levels = _Utils.logger_levels_from_env()
        return Config(format_style, root_level, app_level, levels)


class _RequestIdAdapter(LoggerAdapter):
    """Adapter for adding a request id to log messages."""

    def process(self, msg: str, kwargs: MutableMapping[str, Any]) -> tuple[str, MutableMapping[str, Any]]:
        """Implement process."""
        extra: Mapping[str, object] = self.extra if self.extra is not None else {}
        rid = extra.get("request_id")
        if rid is None:
            return msg, kwargs
        else:
            if "extra" in kwargs:
                kwargs["extra"] = {**extra, **kwargs["extra"]}
            else:
                kwargs["extra"] = self.extra
            return f"[{rid}] {msg}", kwargs

    @classmethod
    def create(cls, logger: Logger, request_id: str) -> LoggerAdapter:
        """Create a logger adapter that automatically adds the given `request_id` to each log message."""
        return _RequestIdAdapter(logger, {"request_id": request_id})


def configure_logging(cfg: Config = Config.from_env()) -> None:
    """Configures logging library.

    This should run before using a logger. It sets all loggers to
    WARNING, except for our code that will log at INFO. Our code is
    identified by the app root logger `renku_data_services`. All our
    loggers should therefore be children of this logger.

    Level for individual loggers can be overriden using the
    `override_levels` argument. It is a map from logging level to a
    list of logger names. The default reads it from environment
    variables like `DEBUG_LOGGING=logger.name.one,logger.name.two`.
    The pattern is `{LEVEL}_LOGGING` the value is a comma separated
    list of logger names that will be configured to a minimum level of
    `{LEVEL}`.

    """
    # To have a uniform format *everywhere*, there is only one
    # handler. It is added to the root logger. However, imported
    # modules may change this configuration at any time (and they do).
    # This tries to remove all existing handlers as an best effort.
    for ll in _Utils.get_all_loggers():
        ll.setLevel(logging.NOTSET)
        for hdl in ll.handlers:
            ll.removeHandler(hdl)

    handler = logging.StreamHandler()
    handler.setFormatter(cfg.format_style.to_formatter())
    logging.root.setLevel(cfg.root_level)
    logging.root.addHandler(handler)
    logging.getLogger(__app_root_logger).setLevel(cfg.app_level)

    # this is for creating backwards compatibility, ideally these are
    # defined as env vars in the specific process
    logging.getLogger("sanic").setLevel(logging.INFO)
    logging.getLogger("alembic").setLevel(logging.INFO)

    logger = getLogger(__name__)

    # override minimum level for specific loggers
    for level, names in cfg.override_levels.items():
        for name in names:
            logger.info(f"Set threshold level: {name} -> {logging.getLevelName(level)}")
            logging.getLogger(name).setLevel(level)


def print_logger_setting(msg: str | None = None, show_all: bool = False) -> None:
    """Prints the current logger settings.

    It intentionally uses `print` to survive a messed up logger
    config. It prints all loggers that have an explicit set level.
    Others, like those with a `NOT_SET` level and the 'PlaceHolder'
    loggers are not printed.

    """
    l_root = logging.Logger.root
    output = ["================================================================="]
    if msg is not None:
        output.append(f"--- {msg} ---")

    output.append(f"Total logger entries: {len(logging.Logger.manager.loggerDict)}")
    output.append(
        f" * {l_root} (self.level={logging.getLevelName(l_root.level)}, handlers={len(logging.Logger.root.handlers)})"
    )
    for name in logging.Logger.manager.loggerDict:
        ll = logging.Logger.manager.loggerDict[name]
        match ll:
            case logging.Logger() as logger:
                level_name = logging.getLevelName(logger.level)
                eff_level_name = logging.getLevelName(ll.getEffectiveLevel())
                show_item = logger.level != logging.NOTSET
                handlers = logger.handlers
            case logging.PlaceHolder():
                level_name = "{NOT_SET}"
                eff_level_name = "{PlaceHolder}"
                show_item = False
                handlers = []

        if show_all or show_item:
            output.append(f" * Logger({name} @{eff_level_name}, self.level={level_name}, handlers={len(handlers)})")
    output.append("=================================================================")
    print("\n".join(output))
