"""Tests for MCP response policy helpers."""

import os
from unittest.mock import patch

from unifi_mcp_shared.response_policy import (
    resolve_mcp_content_mode,
    should_redact_response_sensitive_fields,
)


def test_mcp_content_mode_defaults_to_adaptive():
    assert resolve_mcp_content_mode("network", env={}) == "adaptive"


def test_server_specific_mcp_content_mode_wins():
    env = {
        "UNIFI_MCP_CONTENT_MODE": "compat",
        "UNIFI_NETWORK_MCP_CONTENT_MODE": "compact",
    }
    assert resolve_mcp_content_mode("network", env=env) == "compact"


def test_global_mcp_content_mode_is_fallback():
    assert resolve_mcp_content_mode("protect", env={"UNIFI_MCP_CONTENT_MODE": "compat"}) == "compat"


def test_config_mcp_content_mode_is_fallback():
    config = {"policy": {"response": {"mcp_content_mode": "compact"}}}
    assert resolve_mcp_content_mode("access", config=config, env={}) == "compact"


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
