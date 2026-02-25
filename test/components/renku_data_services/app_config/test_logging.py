"""Tests for the app_config.logging module."""

import json
import logging

from renku_data_services.app_config.logging import (
    Config,
    LogFormatStyle,
    _RenkuJsonFormatter,
    _RenkuLogFormatter,
    _RequestIdFilter,
    set_request_id,
    set_trace_id,
)

logger = logging.getLogger(__name__)

sample_record = logging.LogRecord(
    name="a.b.c",
    level=logging.INFO,
    lineno=23,
    msg="this is a msg",
    pathname="a/b.py",
    args=None,
    exc_info=None,
)
_RequestIdFilter().filter(sample_record)


class TestHandler(logging.Handler):
    def __init__(self) -> None:
        logging.Handler.__init__(self)
        self.records = []

    def emit(self, record) -> None:
        self.records.append(record)

    def reset(self) -> None:
        self.records = []


def make_logger(name: str, level: int) -> tuple[logging.Logger, TestHandler]:
    logger = logging.Logger(name, level)
    hdl = TestHandler()
    logger.addHandler(hdl)
    logger.addFilter(_RequestIdFilter())
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
    for level in logging._nameToLevel:
        monkeysession.setenv(f"{level}_LOGGING", "")

    cfg = Config.from_env()
    assert cfg.app_level == logging.INFO
    assert cfg.root_level == logging.WARNING
    assert cfg.format_style == LogFormatStyle.plain
    assert cfg.override_levels == {}


def test_config_from_env(monkeysession) -> None:
    for level in logging._nameToLevel:
        monkeysession.setenv(f"{level}_LOGGING", "")

    monkeysession.setenv("DEBUG_LOGGING", "renku_data_services.test")
    monkeysession.setenv("LOG_APP_LEVEL", "WARN")
    monkeysession.setenv("LOG_FORMAT_STYLE", "Json")

    cfg = Config.from_env()
    assert cfg.app_level == logging.WARNING
    assert cfg.root_level == logging.WARNING
    assert cfg.format_style == LogFormatStyle.json
    assert cfg.override_levels == {10: {"renku_data_services.test"}}


def test_log_with_request_id() -> None:
    logger, hdl = make_logger("test.logger", logging.INFO)
    set_request_id("req_id_1")
    logger.info("hello world")
    assert len(hdl.records) == 1
    record = hdl.records[0]
    assert record.request_id == "req_id_1"
    assert record.getMessage() == "hello world"


def test_log_with_trace_id() -> None:
    logger, hdl = make_logger("test.logger", logging.INFO)
    trace_id = "trace_id"
    set_trace_id(trace_id)
    logger.info("hello world")
    assert len(hdl.records) == 1
    record = hdl.records[0]
    assert record.trace_id == trace_id


def test_log_request_id_json() -> None:
    logger, hdl = make_logger("test.logger", logging.INFO)
    set_request_id("test_req_2")
    logger.info("hello world")
    assert len(hdl.records) == 1
    record = hdl.records[0]
    js = json.loads(_RenkuJsonFormatter().format(record))
    assert js["request_id"] == "test_req_2"


def test_log_trace_id_json() -> None:
    logger, hdl = make_logger("test.logger", logging.INFO)
    trace_id = "trace_id"
    set_trace_id(trace_id)
    logger.info("hello world")
    assert len(hdl.records) == 1
    record = hdl.records[0]
    js = json.loads(_RenkuJsonFormatter().format(record))
    assert js["trace_id"] == trace_id


def test_config_update_levels() -> None:
    cfg1 = Config(override_levels={10: {"a", "b"}, 20: {"c"}})
    cfg1.update_override_levels({10: {"c"}, 20: {"b"}})
    assert cfg1.override_levels == {10: {"a", "c"}, 20: {"b"}}
