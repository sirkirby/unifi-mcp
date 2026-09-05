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
        "rtsp_alias": "stream-alias",
        "rtsps_url": "rtsps://nvr.local:7441/stream-alias",
        "rtsp_url": "rtsp://nvr.local:7447/stream-alias",
        "rtsps_streams": {"high": "rtsps://nvr.local:7441/high"},
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
    assert redacted["rtsp_alias"] == REDACTED
    assert redacted["rtsps_url"] == REDACTED
    assert redacted["rtsp_url"] == REDACTED
    assert redacted["rtsps_streams"] == REDACTED
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


def test_redact_sensitive_false_returns_values_unchanged() -> None:
    payload = {"password": "secret", "nested": [{"token": "tok"}]}

    assert redact_sensitive_fields(payload, redact_sensitive=False) == payload


def test_preserves_none_sensitive_values() -> None:
    payload = {"token": None, "pin_code": None}

    assert redact_sensitive_fields(payload) == payload


def test_redact_value_redacts_sensitive_keys_only() -> None:
    assert redact_value("x_passphrase", "wifi-secret") == REDACTED
    assert redact_value("token", "tok") == REDACTED
    assert redact_value("name", "Guest") == "Guest"
    # None is exempt (nothing to hide), matching redact_sensitive_fields.
    assert redact_value("token", None) is None
    # Disabling redaction returns the raw value untouched.
    assert redact_value("token", "tok", redact_sensitive=False) == "tok"


def test_does_not_redact_preshared_keys_enabled_flag() -> None:
    # The boolean toggle is non-sensitive config, unlike the keys list itself.
    assert is_sensitive_key("private_preshared_keys_enabled") is False
    assert is_sensitive_key("private_preshared_keys") is True


def test_redacts_role_infixed_private_and_preshared_keys() -> None:
    # Real UniFi networkconf field names (WireGuard manual mode) carry a role
    # infix (wireguard_client_*/wireguard_server_*) that the bare exact-match
    # vocabulary missed, leaking key material — see issue #351.
    assert is_sensitive_key("wireguard_client_private_key") is True
    assert is_sensitive_key("wireguard_server_private_key") is True
    assert is_sensitive_key("x_wireguard_private_key") is True
    assert is_sensitive_key("wireguard_client_preshared_key") is True
    assert is_sensitive_key("wireguard_server_preshared_key") is True
    # Public keys are not secret and must stay visible.
    assert is_sensitive_key("public_key") is False
    assert is_sensitive_key("wireguard_client_public_key") is False


def test_redacts_underscore_split_preshared_key_fields() -> None:
    # Real UniFi networkconf field for L2TP/IPsec VPNs: "pre" and "shared" are
    # split into separate underscore-delimited segments, so the bare
    # "preshared" qualifier match misses it and the PSK leaks in cleartext.
    assert is_sensitive_key("x_ipsec_pre_shared_key") is True
    assert is_sensitive_key("ipsec_pre_shared_key") is True
    assert is_sensitive_key("remote_pre_shared_key") is True


def test_redacts_vpn_config_blob_fields() -> None:
    # The secret rides inside a config-blob string under an innocuous key
    # (issue #351): the whole blob field is treated as a secret (suppression).
    assert is_sensitive_key("openvpn_configuration") is True
    assert is_sensitive_key("wireguard_client_configuration_file") is True
    assert is_sensitive_key("wireguard_server_configuration_file") is True
    # Sibling metadata keys are NOT secret and must remain visible.
    assert is_sensitive_key("openvpn_configuration_status") is False
    assert is_sensitive_key("openvpn_configuration_filename") is False
    assert is_sensitive_key("wireguard_client_configuration_filename") is False
    assert is_sensitive_key("wireguard_client_mode") is False


def test_redaction_marker_paths_reports_only_sensitive_marker_values() -> None:
    payload = {
        "update_data": {
            "x_passphrase": REDACTED,
            "name": REDACTED,
            "nested": [{"community": REDACTED}, {"community_id": REDACTED}],
        }
    }

    assert redaction_marker_paths(payload) == ["update_data.x_passphrase", "update_data.nested[0].community"]


def test_redacts_device_ssh_and_management_credentials() -> None:
    """The mgmt site setting carries the device-SSH password hash and the
    management key; ``passwd`` is a spelling the vocabulary did not know."""
    payload = {
        "x_ssh_sha512passwd": "$6$hash",
        "x_ssh_md5passwd": "$1$hash",
        "x_ssh_password": "clear",
        "x_mgmt_key": "0123456789abcdef",
        "x_api_token": "tok",
    }
    redacted = redact_sensitive_fields(payload)
    assert all(value == REDACTED for value in redacted.values()), redacted
    assert is_sensitive_key("x_ssh_bcrypt_passwd") and is_sensitive_key("xSshSha512Passwd")
    assert is_sensitive_key("xMgmtKey")


def test_boolean_flags_named_after_a_secret_stay_visible() -> None:
    """``x_ssh_auth_password_enabled`` is state an operator needs; a string
    under a secret-looking name is still hidden, and the key itself stays
    sensitive so the write-back guard is unchanged."""
    redacted = redact_sensitive_fields(
        {"x_ssh_auth_password_enabled": True, "x_ssh_password": "clear", "x_secret_enabled": "s3cr3t"}
    )
    assert redacted["x_ssh_auth_password_enabled"] is True
    assert redacted["x_ssh_password"] == REDACTED
    assert redacted["x_secret_enabled"] == REDACTED
    assert is_sensitive_key("x_ssh_auth_password_enabled") is True
    assert redact_value("x_ssh_auth_password_enabled", False) is False
    # A bool is never the marker, so the write-back guard sees the same paths as before.
    assert redaction_marker_paths({"x_ssh_auth_password_enabled": True, "x_ssh_password": REDACTED}) == [
        "x_ssh_password"
    ]


def test_ssh_public_keys_stay_visible() -> None:
    assert is_sensitive_key("x_ssh_keys") is False
    assert redact_sensitive_fields({"x_ssh_keys": [{"name": "laptop", "type": "ssh-ed25519", "key": "AAAA"}]}) == {
        "x_ssh_keys": [{"name": "laptop", "type": "ssh-ed25519", "key": "AAAA"}]
    }
