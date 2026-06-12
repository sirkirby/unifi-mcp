from copy import deepcopy

from unifi_core.redaction import (
    REDACTED,
    is_sensitive_key,
    redact_sensitive_fields,
    redact_value,
    redaction_marker_paths,
)


def test_redacts_exact_and_compound_sensitive_keys() -> None:
    payload = {
        "x_passphrase": "wifi-secret",
        "privateKey": "wg-private",
        "private_preshared_keys": [{"id": "k1", "psk": "wifi-psk"}],
        "private_preshared_keys_enabled": True,
        "wireguard_private_key": "wg-private",
        "preshared_key": "wg-psk",
        "x_iapp_key": "wlan-iapp",
        "apiToken": "api-token",
        "community": "snmp-secret",
        "tls_crypt": "tls-secret",
        "pin_code": "123456",
        "name": "Guest",
    }

    redacted = redact_sensitive_fields(payload)

    assert redacted["x_passphrase"] == REDACTED
    assert redacted["privateKey"] == REDACTED
    assert redacted["private_preshared_keys"] == REDACTED
    # The boolean feature flag is NOT a secret — redacting it would hide
    # useful, non-sensitive configuration state from the agent.
    assert redacted["private_preshared_keys_enabled"] is True
    assert redacted["wireguard_private_key"] == REDACTED
    assert redacted["preshared_key"] == REDACTED
    assert redacted["x_iapp_key"] == REDACTED
    assert redacted["apiToken"] == REDACTED
    assert redacted["community"] == REDACTED
    assert redacted["tls_crypt"] == REDACTED
    assert redacted["pin_code"] == REDACTED
    assert redacted["name"] == "Guest"


def test_recurses_into_nested_dicts_and_lists_without_mutating_input() -> None:
    original = {
        "outer": {
            "wireguard": [
                {"private_key": "private"},
                {"server": "vpn.example.test"},
            ],
        }
    }
    snapshot = deepcopy(original)

    redacted = redact_sensitive_fields(original)

    assert redacted["outer"]["wireguard"][0]["private_key"] == REDACTED
    assert redacted["outer"]["wireguard"][1]["server"] == "vpn.example.test"
    assert original == snapshot


def test_does_not_redact_unrelated_key_words() -> None:
    payload = {
        "network_key": "sort-key",
        "monkey": "value",
        "public_key": "public-key-material",
        "token_count": 4,
        "community_id": "community-1",
    }

    assert redact_sensitive_fields(payload) == payload
    assert is_sensitive_key("network_key") is False
    assert is_sensitive_key("monkey") is False
    assert is_sensitive_key("public_key") is False
    assert is_sensitive_key("token_count") is False
    assert is_sensitive_key("community_id") is False


def test_include_sensitive_returns_values_unchanged() -> None:
    payload = {"password": "secret", "nested": [{"token": "tok"}]}

    assert redact_sensitive_fields(payload, include_sensitive=True) == payload


def test_preserves_none_sensitive_values() -> None:
    payload = {"token": None, "pin_code": None}

    assert redact_sensitive_fields(payload) == payload


def test_redact_value_redacts_sensitive_keys_only() -> None:
    assert redact_value("x_passphrase", "wifi-secret") == REDACTED
    assert redact_value("token", "tok") == REDACTED
    assert redact_value("name", "Guest") == "Guest"
    # None is exempt (nothing to hide), matching redact_sensitive_fields.
    assert redact_value("token", None) is None
    # The opt-out returns the raw value untouched.
    assert redact_value("token", "tok", include_sensitive=True) == "tok"


def test_does_not_redact_preshared_keys_enabled_flag() -> None:
    # The boolean toggle is non-sensitive config, unlike the keys list itself.
    assert is_sensitive_key("private_preshared_keys_enabled") is False
    assert is_sensitive_key("private_preshared_keys") is True


def test_redaction_marker_paths_reports_only_sensitive_marker_values() -> None:
    payload = {
        "update_data": {
            "x_passphrase": REDACTED,
            "name": REDACTED,
            "nested": [{"community": REDACTED}, {"community_id": REDACTED}],
        }
    }

    assert redaction_marker_paths(payload) == ["update_data.x_passphrase", "update_data.nested[0].community"]
