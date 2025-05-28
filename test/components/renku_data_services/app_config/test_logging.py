"""Tests for the app_config.logging module."""

import json
import logging as ll
from logging import LogRecord

from renku_data_services.app_config.logging import (
    Config,
    LogFormatStyle,
    _RenkuJsonFormatter,
    _RenkuLogFormatter,
    with_request_id,
)

logger = ll.getLogger(__name__)

sample_record = LogRecord(
    name="a.b.c",
    level=ll.INFO,
    lineno=23,
    msg="this is a msg",
    pathname="a/b.py",
    args=None,
    exc_info=None,
)


class TestHandler(ll.Handler):
    def __init__(self) -> None:
        ll.Handler.__init__(self)
        self.records = []

    def emit(self, record) -> None:
        self.records.append(record)

    def reset(self) -> None:
        self.records = []


def make_logger(name: str, level: int) -> tuple[ll.Logger, TestHandler]:
    logger = ll.Logger(name, level)
    hdl = TestHandler()
    logger.addHandler(hdl)
    return logger, hdl


def test_json_formatter_creates_json() -> None:
    fmt = _RenkuJsonFormatter()
    s = fmt.format(sample_record)
    js = json.loads(s)

    assert js["timestamp"] is not None
    assert js["level"] == "INFO"
    assert js["name"] == "a.b.c"
    assert js["pathname"] == "a/b.py"
    assert js["module"] == "b"


def test_plain_formatter() -> None:
    fmt = _RenkuLogFormatter()
    s = fmt.format(sample_record)
    assert "INFO" in s
    assert "a.b.c" in s
    assert sample_record.getMessage() in s


def test_default_config(monkeysession) -> None:
    for level in ll._nameToLevel:
        monkeysession.setenv(f"{level}_LOGGING", "")

    cfg = Config.from_env()
    assert cfg.app_level == ll.INFO
    assert cfg.root_level == ll.WARNING
    assert cfg.format_style == LogFormatStyle.plain
    assert cfg.override_levels == {}


def test_config_from_env(monkeysession) -> None:
    for level in ll._nameToLevel:
        monkeysession.setenv(f"{level}_LOGGING", "")

    monkeysession.setenv("DEBUG_LOGGING", "renku_data_services.test")
    monkeysession.setenv("LOG_APP_LEVEL", "WARN")
    monkeysession.setenv("LOG_FORMAT_STYLE", "Json")

    cfg = Config.from_env()
    assert cfg.app_level == ll.WARNING
    assert cfg.root_level == ll.WARNING
    assert cfg.format_style == LogFormatStyle.json
    assert cfg.override_levels == {10: set(["renku_data_services.test"])}


def test_log_with_request_id() -> None:
    logger, hdl = make_logger("test.logger", ll.INFO)
    logger = with_request_id(logger, "req1")
    logger.info("hello world")
    assert len(hdl.records) == 1
    record = hdl.records[0]
    assert record.getMessage() == "[req1] hello world"


def test_log_request_id_json() -> None:
    logger, hdl = make_logger("test.logger", ll.INFO)
    logger = with_request_id(logger, "req1")
    logger.info("hello world")
    assert len(hdl.records) == 1
    record = hdl.records[0]
    js = json.loads(_RenkuJsonFormatter().format(record))
    assert js["request_id"] == "req1"

    hdl.reset()
    logger.info("hello again", extra={"foo": 2})
    assert len(hdl.records) == 1
    record = hdl.records[0]
    js = json.loads(_RenkuJsonFormatter().format(record))
    assert js["request_id"] == "req1"
    assert js["foo"] == 2


def test_config_update_levels() -> None:
    cfg1 = Config(override_levels={10: set(["a", "b"]), 20: set(["c"])})
    cfg1.update_override_levels({10: set(["c"]), 20: set(["b"])})
    assert cfg1.override_levels == {10: set(["a", "c"]), 20: set(["b"])}
