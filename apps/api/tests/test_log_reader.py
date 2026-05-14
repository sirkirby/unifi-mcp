"""Tests for the tail-of-file log reader."""

from __future__ import annotations

import json
from pathlib import Path

from unifi_api.services.log_reader import LogReader


def _write_lines(path: Path, entries: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


def test_tail_returns_most_recent_first(tmp_path: Path) -> None:
    log = tmp_path / "app.log"
    _write_lines(
        log,
        [
            {"ts": "2026-04-30T00:00:01Z", "level": "INFO", "logger": "a", "event": "first"},
            {"ts": "2026-04-30T00:00:02Z", "level": "INFO", "logger": "a", "event": "second"},
            {"ts": "2026-04-30T00:00:03Z", "level": "INFO", "logger": "a", "event": "third"},
        ],
    )

    entries = LogReader(log).tail(limit=10)

    assert len(entries) == 3
    assert [e["event"] for e in entries] == ["third", "second", "first"]


def test_tail_respects_limit(tmp_path: Path) -> None:
    log = tmp_path / "app.log"
    _write_lines(
        log,
        [{"ts": f"2026-04-30T00:00:{i:02d}Z", "level": "INFO", "logger": "a", "event": f"e{i}"} for i in range(10)],
    )

    entries = LogReader(log).tail(limit=3)

    assert len(entries) == 3
    assert [e["event"] for e in entries] == ["e9", "e8", "e7"]


def test_filter_by_level(tmp_path: Path) -> None:
    log = tmp_path / "app.log"
    _write_lines(
        log,
        [
            {"ts": "2026-04-30T00:00:01Z", "level": "INFO", "logger": "a", "event": "i1"},
            {"ts": "2026-04-30T00:00:02Z", "level": "WARNING", "logger": "a", "event": "w1"},
            {"ts": "2026-04-30T00:00:03Z", "level": "INFO", "logger": "a", "event": "i2"},
        ],
    )

    reader = LogReader(log)

    upper = reader.tail(level="WARNING")
    assert len(upper) == 1
    assert upper[0]["level"] == "WARNING"
    assert upper[0]["event"] == "w1"

    # Case-insensitive
    lower = reader.tail(level="warning")
    assert len(lower) == 1
    assert lower[0]["event"] == "w1"


def test_filter_by_logger(tmp_path: Path) -> None:
    log = tmp_path / "app.log"
    _write_lines(
        log,
        [
            {"ts": "2026-04-30T00:00:01Z", "level": "INFO", "logger": "a", "event": "a1"},
            {"ts": "2026-04-30T00:00:02Z", "level": "INFO", "logger": "b", "event": "b1"},
            {"ts": "2026-04-30T00:00:03Z", "level": "INFO", "logger": "a", "event": "a2"},
        ],
    )

    entries = LogReader(log).tail(logger="a")

    assert len(entries) == 2
    assert all(e["logger"] == "a" for e in entries)
    assert [e["event"] for e in entries] == ["a2", "a1"]


def test_filter_by_q_substring(tmp_path: Path) -> None:
    log = tmp_path / "app.log"
    _write_lines(
        log,
        [
            {"ts": "2026-04-30T00:00:01Z", "level": "INFO", "logger": "a", "event": "haystack"},
            {"ts": "2026-04-30T00:00:02Z", "level": "INFO", "logger": "a", "event": "find the needle here"},
            {"ts": "2026-04-30T00:00:03Z", "level": "INFO", "logger": "a", "event": "another"},
        ],
    )

    entries = LogReader(log).tail(q="needle")

    assert len(entries) == 1
    assert entries[0]["event"] == "find the needle here"


def test_missing_file_returns_empty(tmp_path: Path) -> None:
    reader = LogReader(tmp_path / "no_such.log")

    assert reader.tail() == []
    assert reader.size_bytes == 0
