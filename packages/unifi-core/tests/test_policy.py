"""Tests for response redaction policy resolution."""

import logging

from unifi_core.policy import should_redact_sensitive_fields


def test_response_redaction_defaults_to_true():
    assert should_redact_sensitive_fields("network", env={}) is True


def test_global_false_disables_response_redaction():
    env = {"UNIFI_REDACT_SENSITIVE_FIELDS": "false"}

    assert should_redact_sensitive_fields("network", env=env) is False


def test_server_specific_true_overrides_global_false():
    env = {
        "UNIFI_REDACT_SENSITIVE_FIELDS": "false",
        "UNIFI_NETWORK_REDACT_SENSITIVE_FIELDS": "true",
    }

    assert should_redact_sensitive_fields("network", env=env) is True


def test_access_server_specific_false_disables_response_redaction():
    env = {"UNIFI_ACCESS_REDACT_SENSITIVE_FIELDS": "false"}

    assert should_redact_sensitive_fields("access", env=env) is False


def test_api_server_specific_false_disables_response_redaction():
    env = {"UNIFI_API_REDACT_SENSITIVE_FIELDS": "false"}

    assert should_redact_sensitive_fields("api", env=env) is False


def test_config_false_disables_response_redaction_when_env_unset():
    config = {"policy": {"response": {"redact_sensitive_fields": False}}}

    assert should_redact_sensitive_fields("network", config=config, env={}) is False


def test_config_true_enables_response_redaction_when_env_unset():
    config = {"policy": {"response": {"redact_sensitive_fields": "true"}}}

    assert should_redact_sensitive_fields("network", config=config, env={}) is True


def test_empty_env_value_is_treated_as_unset_and_falls_through_to_config():
    # An empty surface override must not mask a config-level disable.
    env = {"UNIFI_NETWORK_REDACT_SENSITIVE_FIELDS": ""}
    config = {"policy": {"response": {"redact_sensitive_fields": False}}}

    assert should_redact_sensitive_fields("network", config=config, env=env) is False


def test_empty_env_value_does_not_warn(caplog):
    env = {"UNIFI_NETWORK_REDACT_SENSITIVE_FIELDS": "   "}

    with caplog.at_level(logging.WARNING, logger="unifi_core.policy"):
        # Falls through to the default True with no invalid-value warning.
        assert should_redact_sensitive_fields("network", env=env) is True

    assert "Invalid value" not in caplog.text


def test_invalid_env_value_fails_closed_with_warning(caplog):
    env = {"UNIFI_NETWORK_REDACT_SENSITIVE_FIELDS": "raw"}

    with caplog.at_level(logging.WARNING, logger="unifi_core.policy"):
        assert should_redact_sensitive_fields("network", env=env) is True

    assert "UNIFI_NETWORK_REDACT_SENSITIVE_FIELDS" in caplog.text
    assert "treating as redacted" in caplog.text


def test_invalid_config_value_fails_closed_with_warning(caplog):
    config = {"policy": {"response": {"redact_sensitive_fields": "raw"}}}

    with caplog.at_level(logging.WARNING, logger="unifi_core.policy"):
        assert should_redact_sensitive_fields("network", config=config, env={}) is True

    assert "policy.response.redact_sensitive_fields" in caplog.text
    assert "treating as redacted" in caplog.text
