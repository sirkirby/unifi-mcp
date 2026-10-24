"""Tests for MCP response policy helpers."""

import os
from unittest.mock import patch

import pytest
from unifi_mcp_shared.response_policy import (
    resolve_mcp_content_mode,
    should_redact_response_sensitive_fields,
)


@pytest.mark.parametrize(
    ("server", "config", "env", "expected"),
    [
        ("network", None, {}, "adaptive"),
        (
            "network",
            None,
            {"UNIFI_MCP_CONTENT_MODE": "compat", "UNIFI_NETWORK_MCP_CONTENT_MODE": "compact"},
            "compact",
        ),
        ("protect", None, {"UNIFI_MCP_CONTENT_MODE": "compat"}, "compat"),
        ("access", {"policy": {"response": {"mcp_content_mode": "compact"}}}, {}, "compact"),
    ],
)
def test_resolve_mcp_content_mode(server, config, env, expected):
    assert resolve_mcp_content_mode(server, config=config, env=env) == expected


def test_invalid_mcp_content_mode_falls_back_to_adaptive(caplog):
    assert resolve_mcp_content_mode("network", env={"UNIFI_MCP_CONTENT_MODE": "invalid"}) == "adaptive"
    assert "UNIFI_MCP_CONTENT_MODE" in caplog.text


def test_response_redaction_defaults_to_true():
    with patch.dict(os.environ, {}, clear=True):
        assert should_redact_response_sensitive_fields("network") is True


def test_redaction_disabled_config_returns_false():
    config = {"policy": {"response": {"redact_sensitive_fields": False}}}

    with patch.dict(os.environ, {}, clear=True):
        assert should_redact_response_sensitive_fields("network", config=config) is False
