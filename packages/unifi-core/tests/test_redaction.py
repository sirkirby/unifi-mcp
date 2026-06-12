from copy import deepcopy

from unifi_core.redaction import REDACTED, is_sensitive_key, redact_sensitive_fields


def test_redacts_exact_and_compound_sensitive_keys() -> None:
    payload = {
        "x_passphrase": "wifi-secret",
        "privateKey": "wg-private",
        "preshared_key": "wg-psk",
        "apiToken": "api-token",
        "tls_crypt": "tls-secret",
        "pin_code": "123456",
        "name": "Guest",
    }

    redacted = redact_sensitive_fields(payload)

    assert redacted["x_passphrase"] == REDACTED
    assert redacted["privateKey"] == REDACTED
    assert redacted["preshared_key"] == REDACTED
    assert redacted["apiToken"] == REDACTED
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
    }

    assert redact_sensitive_fields(payload) == payload
    assert is_sensitive_key("network_key") is False
    assert is_sensitive_key("monkey") is False
    assert is_sensitive_key("public_key") is False
    assert is_sensitive_key("token_count") is False


def test_include_sensitive_returns_values_unchanged() -> None:
    payload = {"password": "secret", "nested": [{"token": "tok"}]}

    assert redact_sensitive_fields(payload, include_sensitive=True) == payload
