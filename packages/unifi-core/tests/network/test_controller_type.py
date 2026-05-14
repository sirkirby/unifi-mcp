"""Tests for unifi_core.network.controller_type.resolve_controller_type."""

from __future__ import annotations

import logging

import pytest
from unifi_core.network.controller_type import (
    VALID_CONTROLLER_TYPES,
    resolve_controller_type,
)


def test_default_is_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UNIFI_CONTROLLER_TYPE", raising=False)
    assert resolve_controller_type() == "auto"


@pytest.mark.parametrize("value", ["auto", "proxy", "direct"])
def test_accepts_valid_values(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNIFI_CONTROLLER_TYPE", value)
    assert resolve_controller_type() == value


def test_normalizes_case(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNIFI_CONTROLLER_TYPE", "PROXY")
    assert resolve_controller_type() == "proxy"


def test_invalid_falls_back_to_auto_with_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("UNIFI_CONTROLLER_TYPE", "udmpro")
    with caplog.at_level(logging.WARNING, logger="unifi_core.network.controller_type"):
        assert resolve_controller_type() == "auto"
    assert any("Invalid UNIFI_CONTROLLER_TYPE" in rec.message for rec in caplog.records)


def test_valid_values_constant_matches_resolver() -> None:
    assert VALID_CONTROLLER_TYPES == frozenset({"auto", "proxy", "direct"})
