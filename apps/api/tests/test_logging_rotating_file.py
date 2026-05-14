"""Tests for the rotating file handler and `logger` field in JsonFormatter."""

import json

from unifi_api.logging import (
    attach_rotating_file_handler,
    configure_logging,
    get_logger,
)


def test_attaches_handler_and_writes_json(tmp_path) -> None:
    log_path = tmp_path / "app.log"
    configure_logging(level="INFO")
    handler = attach_rotating_file_handler(
        path=log_path,
        max_bytes=10_485_760,
        backup_count=2,
    )
    log = get_logger("test_logger")
    log.info("rotating_event")
    handler.flush()
    handler.close()

    contents = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert contents, "expected at least one JSON line written to the rotating file"
    payload = json.loads(contents[-1])
    assert payload["event"] == "rotating_event"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test_logger"


def test_creates_parent_directories(tmp_path) -> None:
    log_path = tmp_path / "nested" / "subdir" / "app.log"
    assert not log_path.parent.exists()
    configure_logging(level="INFO")
    handler = attach_rotating_file_handler(
        path=log_path,
        max_bytes=10_485_760,
        backup_count=2,
    )
    assert log_path.parent.exists()
    assert log_path.parent.is_dir()

    log = get_logger("nested_logger")
    log.info("nested_event")
    handler.flush()
    handler.close()
    assert log_path.exists()


def test_logger_field_in_stderr_json(capsys) -> None:
    configure_logging(level="INFO")
    log = get_logger("my.module")
    log.info("foo")
    captured = capsys.readouterr().err.strip().splitlines()
    assert captured, "expected one JSON log line on stderr"
    payload = json.loads(captured[-1])
    assert payload["logger"] == "my.module"
