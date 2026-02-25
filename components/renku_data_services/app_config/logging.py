"""Logging configuration.

This is a central place for configuring the logging library, so that
all log messages have the same format. The intention is to use it like
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

Additionally, with `set_request_id` a request id can be provided that
will be injected into every log record. This id is managed by a
ContextVar to be retained correctly in async contexts. The same applies
to `set_trace_id`.

Before accessing loggers, run the `configure_logging()` method to
configure loggers appropriately.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final, cast, final

from renku_data_services.errors.errors import ConfigurationError

# Re-exports to be used in other modules
ERROR = logging.ERROR
Logger = logging.Logger

__app_root_logger: Final[str] = "renku_data_services"

_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id")
_trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id")


def getLogger(name: str) -> logging.Logger:
    """Return a logger with the name prefixed with our app name, if not already done."""
    if name.startswith(__app_root_logger + "."):
        return logging.getLogger(name)
    else:
        return logging.getLogger(f"{__app_root_logger}.{name}")


def set_request_id(request_id: str | None) -> None:
    """Provide the request_id as a context-sensitive global variable.

    The id will be used in subsequent logging statements.
    """
    if request_id is None:
        _request_id_var.set("")
    else:
        _request_id_var.set(request_id)


def set_trace_id(trace_id: str | None) -> None:
    """Set a trace id for the current context that will be logged in subsequent logging statements."""
    if trace_id is None:
        _trace_id_var.set("")
    else:
        _trace_id_var.set(trace_id)


class _RenkuLogFormatter(logging.Formatter):
    """Custom formatter.

    It is used to encapsulate the formatting options and to use
    datetime instead of struct_time.
    """

    def __init__(self) -> None:
        super().__init__(
            fmt=(
                "%(asctime)s [%(levelname)s] %(process)d/%(threadName)s "
                "%(name)s (%(filename)s:%(lineno)d) [%(request_id)s][%(trace_id)s] - %(message)s"
            ),
            datefmt="%Y-%m-%dT%H:%M:%S.%f%z",
        )

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        """Overridden to format the time string for %(asctime) interpolator."""
        ct = datetime.fromtimestamp(record.created)
        return ct.strftime(cast(str, self.datefmt))


class _RenkuJsonFormatter(_RenkuLogFormatter):
    """Formatter to produce json log messages."""

    fields: Final[set[str]] = {"name", "levelno", "pathname", "module", "filename", "lineno"}
    default_fields: Final[set[str]] = fields.union({"exc_info", "stack_info", "asctime", "message", "msg"})

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record."""
        super().format(record)
        return json.dumps(self._to_dict(record), default=str)

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
    def from_env(cls, prefix: str = "", default: str = "plain") -> LogFormatStyle:
        """Read the format style from env var `LOG_FORMAT`."""
        str_value = os.environ.get(f"{prefix}LOG_FORMAT_STYLE", default).lower()
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
    def _logger_list_from_env(cls, level: int, prefix: str) -> set[str]:
        level_name = logging._levelToName.get(level)
        if level_name is None:
            return set()

        key = f"{prefix}{level_name.upper()}_LOGGING"
        value = os.environ.get(key, "").strip()
        if value == "":
            return set()

        return set([n.strip() for n in value.split(",")])

    @classmethod
    def logger_levels_from_env(cls, prefix: str) -> dict[int, set[str]]:
        config = {}
        for level in list(logging._levelToName.keys()):
            logger_names = cls._logger_list_from_env(level, prefix)
            if logger_names != set():
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
    override_levels: dict[int, set[str]] = field(default_factory=dict)

    def update_override_levels(self, others: dict[int, set[str]]) -> None:
        """Applies the given override levels to this config."""
        other_loggers = {e for s in others.values() for e in s}
        self.remove_override_loggers(other_loggers)
        for level, names in others.items():
            cur_names = self.override_levels.get(level) or set()
            cur_names = names.union(cur_names)
            self.override_levels.update({level: cur_names})

    def remove_override_loggers(self, loggers: set[str]) -> None:
        """Removes the given loggers from the override levels config."""
        next_levels = {}
        for level, names in self.override_levels.items():
            next_names = names.difference(loggers)
            if next_names != set():
                next_levels.update({level: next_names})
        self.override_levels = next_levels

    @classmethod
    def from_env(cls, prefix: str = "") -> Config:
        """Return a config obtained from environment variables."""
        default = cls()
        root_level_var = os.environ.get(f"{prefix}LOG_ROOT_LEVEL")
        root_level = _Utils.get_numeric_level(root_level_var) if root_level_var else default.root_level
        app_level_var = os.environ.get(f"{prefix}LOG_APP_LEVEL")
        app_level = _Utils.get_numeric_level(app_level_var) if app_level_var else default.app_level
        format_style = LogFormatStyle.from_env(prefix, default.format_style.value)
        levels = _Utils.logger_levels_from_env(prefix)
        return Config(format_style, root_level, app_level, levels)


class _RequestIdFilter(logging.Filter):
    """Hack the request id into the log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        request_id = _request_id_var.get("-")
        record.request_id = request_id
        trace_id = _trace_id_var.get("-")
        record.trace_id = trace_id
        return True


def configure_logging(cfg: Config | None = None) -> None:
    """Configures logging library.

    This should run before using a logger. It sets all loggers to
    WARNING, except for our code that will log at INFO. Our code is
    identified by the app root logger `renku_data_services`. All our
    loggers should therefore be children of this logger.

    Level for individual loggers can be overridden using the
    `override_levels` argument. It is a map from logging level to a
    list of logger names. The default reads it from environment
    variables like `DEBUG_LOGGING=logger.name.one,logger.name.two`.
    The pattern is `{LEVEL}_LOGGING` the value is a comma separated
    list of logger names that will be configured to a minimum level of
    `{LEVEL}`.

    """
    if cfg is None:
        cfg = Config.from_env()

    # NOTE: Capture warning logs from Sanic or other modules by our logger to format them as JSON
    logging.captureWarnings(True)

    # To have a uniform format *everywhere*, there is only one
    # handler. It is added to the root logger. However, imported
    # modules may change this configuration at any time (and they do).
    # This tries to remove all existing handlers as the best effort.
    for logger in _Utils.get_all_loggers():
        logger.setLevel(logging.NOTSET)
        for hdl in logger.handlers:
            logger.removeHandler(hdl)

    handler = logging.StreamHandler()
    handler.setFormatter(cfg.format_style.to_formatter())
    handler.addFilter(_RequestIdFilter())
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
    output = ["=" * 65]
    if msg is not None:
        output.append(msg.center(65, "-"))

    output.append(f"Total logger entries: {len(logging.Logger.manager.loggerDict)}")
    output.append(
        f" * {l_root} (self.level={logging.getLevelName(l_root.level)}, handlers={len(logging.Logger.root.handlers)})"
    )
    for name in logging.Logger.manager.loggerDict:
        logger = logging.Logger.manager.loggerDict[name]
        match logger:
            case logging.Logger():
                level_name = logging.getLevelName(logger.level)
                eff_level_name = logging.getLevelName(logger.getEffectiveLevel())
                show_item = logger.level != logging.NOTSET
                handlers = logger.handlers
            case logging.PlaceHolder():
                level_name = "{NOT_SET}"
                eff_level_name = "{PlaceHolder}"
                show_item = False
                handlers = []

        if show_all or show_item:
            output.append(f" * Logger({name} @{eff_level_name}, self.level={level_name}, handlers={len(handlers)})")
    output.append("" * 65)
    print("\n".join(output))
