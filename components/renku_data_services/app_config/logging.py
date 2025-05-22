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

import logging
import os
from logging import Logger, LoggerAdapter
from typing import Final

import sanic.logging.formatter

__app_root_logger: Final[str] = "renku_data_services"


def getLogger(name: str) -> Logger:
    """Return a logger with the name prefixed with our app name, if not already done."""
    if name.startswith(__app_root_logger + "."):
        return logging.getLogger(name)
    else:
        return logging.getLogger(f"{__app_root_logger}.{name}")


def with_request_id(logger: Logger, request_id: str) -> LoggerAdapter:
    """Amend `logger` adding `request_id` to every log message."""
    return RequestIdAdapter.create(logger, request_id)


def __logger_list(level: int) -> list[str]:
    level_name = logging._levelToName.get(level)
    if level_name is None:
        return []

    key = f"{level_name.upper()}_LOGGING"
    value = os.environ.get(key)
    if value is None:
        return []

    return [n.strip() for n in value.split(",")]


def __logger_levels_from_env() -> dict[int, list[str]]:
    config = {}
    for level in list(logging._levelToName.keys()):
        logger_names = __logger_list(level)
        config.update({level: logger_names})

    return config


def configure_logging(override_levels: dict[int, list[str]] = __logger_levels_from_env()) -> None:
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
    # handler. It is added to the root logger.
    handler = logging.StreamHandler()
    handler.setFormatter(sanic.logging.formatter.AutoFormatter())
    logging.root.setLevel(logging.WARNING)
    for hdl in logging.root.handlers:
        logging.root.removeHandler(hdl)
    logging.root.addHandler(handler)
    logging.getLogger(__app_root_logger).setLevel(logging.INFO)

    # this is for creating backwards compatibility, ideally these are
    # defined as env vars in the specific base
    logging.getLogger("sanic").setLevel(logging.INFO)
    logging.getLogger("alembic").setLevel(logging.INFO)

    logger = getLogger(__name__)

    # override minimum level for specific loggers
    for level, names in override_levels.items():
        for name in names:
            logger.info(f"Set threshold level: {name} -> {logging.getLevelName(level)}")
            logging.getLogger(name).setLevel(level)


def print_logger_setting(msg: str | None = None, show_all: bool = False) -> None:
    """Prints the current logger settings.

    It intentionally using `print` to survive a messed up logger
    config. It prints all loggers that have an explicit set level.
    Others, like those with a `NOT_SET` level and the 'PlaceHolder'
    loggers are not printed.
    """
    l_root = logging.Logger.root
    print("=================================================================")
    if msg is not None:
        print(f"--- {msg} ---")
    print(f"Total logger entries: {len(logging.Logger.manager.loggerDict)}")
    print(
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
            print(f" * Logger({name} @{eff_level_name}, self.level={level_name}, handlers={len(handlers)})")
    print("=================================================================")


class RequestIdAdapter(LoggerAdapter):
    """Adapter for adding a request id to log messages."""

    def process(self, msg, kwargs):
        """Implement process."""
        rid = self.extra.get("request_id") if self.extra is not None else None
        if rid is None:
            return msg, kwargs
        else:
            return f"[{rid}] {msg}", kwargs

    @classmethod
    def create(cls, logger: Logger, request_id: str) -> LoggerAdapter:
        """Create a logger adapter that automatically adds the given `request_id` to each log message."""
        return RequestIdAdapter(logger, {"request_id": request_id})
