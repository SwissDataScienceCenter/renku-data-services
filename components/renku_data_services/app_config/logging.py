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
configure each logger appropriately.
"""

import logging
import os
from logging import Logger, LoggerAdapter

__name_prefix = "renku_data_services."


def getLogger(name: str) -> Logger:
    """Return a logger with the name prefixed with our app name, if not already done."""
    if not name.startswith(__name_prefix):
        return logging.getLogger(f"{__name_prefix}{name}")
    else:
        return logging.getLogger(name)


def with_request_id(logger: Logger, request_id: str) -> LoggerAdapter:
    """Amend the given logger adding the given `request_id` to every log message."""
    return RequestIdAdapter.create(logger, request_id)


def __logger_list(level: int) -> list[str]:
    level_name = logging._levelToName.get(level)
    if level_name is None:
        return []

    key = f"{level_name.upper()}_LOGGING"
    value = os.environ.get(key)
    if value is None:
        return []

    return value.split(",")


def __logger_levels_from_env() -> dict[int, list[str]]:
    levels = [logging.DEBUG, logging.INFO, logging.WARNING]
    config = {}
    for level in levels:
        logger_names = __logger_list(level)
        config.update({level: logger_names})

    return config


def configure_logging(override_levels: dict[int, list[str]] = __logger_levels_from_env()) -> None:
    """Configures logging library.

    This should run once when starting the application. It sets all
    loggers to WARNING, except for our code that will log at INFO.

    Level for individual loggers can be overriden using the
    `override_levels` argument. It is a map from logging level to a
    list of logger names. The default reads it from environment
    variables like `DEBUG_LOGGING=logger.name.one,logger.name.two`.
    The pattern is `{LEVEL}_LOGGING` the value is a comma separated
    list of logger names that will be configured to a minimum level of
    `{LEVEL}`.
    """
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("sanic").setLevel(logging.INFO)
    logging.getLogger("renku_data_services").setLevel(logging.INFO)

    logger = getLogger(__name__)

    # override minimum level for specific loggers
    for level, names in override_levels.items():
        for name in names:
            logger.info(f"Set minimum level: {name} -> {logging._levelToName[level]}")
            logging.getLogger(name).setLevel(level)


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
