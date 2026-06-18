"""Tests for MCP response policy helpers."""

import os
from unittest.mock import patch

from unifi_mcp_shared.response_policy import should_redact_response_sensitive_fields


def test_response_redaction_defaults_to_true():
    with patch.dict(os.environ, {}, clear=True):
        assert should_redact_response_sensitive_fields("network") is True


def test_redaction_disabled_config_returns_false():
    config = {"policy": {"response": {"redact_sensitive_fields": False}}}

    with patch.dict(os.environ, {}, clear=True):
        assert should_redact_response_sensitive_fields("network", config=config) is False
