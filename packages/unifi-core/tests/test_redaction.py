import json
from copy import deepcopy
from urllib.parse import quote

import pytest
from unifi_core.redaction import (
    REDACTED,
    is_sensitive_key,
    redact_sensitive_fields,
    redact_value,
    redaction_marker_paths,
)

from tests.secret_assertions import ESCAPED_SECRET, assert_unrecoverable


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


# ---------------------------------------------------------------------------
# Value scrubbing (error paths)
# ---------------------------------------------------------------------------


def test_collect_secret_values_walks_nested_sensitive_keys():
    from unifi_core.redaction import collect_secret_values

    payload = {
        "enabled": True,
        "x_password": "pw-one",
        "nested": {"community": "pw-two", "port": 161},
        "items": [{"auth_key": "pw-three"}, {"name": "visible"}],
        "pin_code": 1234,
        "token_count": 9,
    }
    assert collect_secret_values(payload) == {"pw-one", "pw-two", "pw-three", "1234"}


def test_collect_secret_values_ignores_bools_and_empty():
    from unifi_core.redaction import collect_secret_values

    assert collect_secret_values({"x_password": "", "psk": None, "secret": True}) == set()


def test_scrub_secret_values_longest_first_and_boundaries():
    from unifi_core.redaction import REDACTED, scrub_secret_values

    text = "rejected {'x_password': 'abc', 'community': 'abcdef'} port 12 of 8443, rc 12"
    out = scrub_secret_values(text, {"abc", "abcdef", "12"})
    assert "abcdef" not in out
    assert "'abc'" not in out
    assert out.count(REDACTED) == 4
    assert "8443" in out  # short-secret boundary match must not shred longer numbers


def test_sanitize_exception_rewrites_args_message_and_cause():
    from unifi_core.redaction import REDACTED, sanitize_exception

    try:
        try:
            raise ValueError("inner hunter2")
        except ValueError as inner:
            raise RuntimeError("outer hunter2") from inner
    except RuntimeError as caught:
        error = caught
    error.message = "attr hunter2"  # type: ignore[attr-defined]
    error.add_note("note hunter2")
    result = sanitize_exception(error, {"hunter2"})

    assert result is error
    assert str(error) == f"outer {REDACTED}"
    assert error.message == f"attr {REDACTED}"  # type: ignore[attr-defined]
    assert error.__notes__ == [f"note {REDACTED}"]
    assert str(error.__cause__) == f"inner {REDACTED}"


def test_sanitize_exception_no_secrets_is_a_no_op():
    from unifi_core.redaction import sanitize_exception

    error = ValueError("unchanged")
    assert sanitize_exception(error, set()) is error
    assert str(error) == "unchanged"


def test_sanitize_exception_redacts_dict_args_like_aiounifi():
    """aiounifi raises ``ERRORS[msg](decoded_response_dict)``; the dict arg must be cleaned too."""
    from unifi_core.redaction import REDACTED, sanitize_exception

    error = ValueError({"meta": {"rc": "error", "msg": "api.err.Invalid hunter2"}, "data": [{"x_password": "hunter2"}]})
    sanitize_exception(error, {"hunter2"})

    assert "hunter2" not in str(error)
    assert error.args[0]["data"][0]["x_password"] == REDACTED
    assert error.args[0]["meta"]["msg"] == f"api.err.Invalid {REDACTED}"


# ---------------------------------------------------------------------------
# Encoded representations of a secret (#660 review)
#
# A message that quotes the offending value through ``repr`` or JSON does not
# contain the literal credential: backslashes are doubled, quotes and newlines
# become escape sequences. Matching only the literal leaves the value fully
# recoverable by decoding, so the scrubber must cover those forms too.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "build_text",
    [
        lambda secret: f"1 validation error [type=string_type, input_value={secret!r}, input_type=str]",
        lambda secret: "controller rejected " + json.dumps({"community": secret}),
        lambda secret: f"input_value={[secret]!r}",
        # Node, Jackson and orjson put the body on the wire with non-ASCII
        # left literal while quotes and backslashes are still escaped.
        lambda secret: "controller rejected " + json.dumps({"community": secret}, ensure_ascii=False),
        # aiounifi renders the raw body on its 429 path with repr(bytes).
        lambda secret: f"Call /set/setting/snmp received 429: {json.dumps({'community': secret}).encode()!r}",
    ],
    ids=["repr", "json", "repr_inside_a_list", "json_non_ascii", "bytes_repr"],
)
def test_scrub_secret_values_removes_encoded_secret(build_text):
    from unifi_core.redaction import REDACTED, scrub_secret_values

    out = scrub_secret_values(build_text(ESCAPED_SECRET), {ESCAPED_SECRET})

    assert REDACTED in out
    assert_unrecoverable(out, ESCAPED_SECRET)


def test_sanitize_exception_scrubs_repr_escaped_secret():
    from unifi_core.redaction import sanitize_exception

    error = ValueError(f"controller rejected {{'x_password': {ESCAPED_SECRET!r}}}")

    sanitize_exception(error, {ESCAPED_SECRET})

    assert_unrecoverable(str(error), ESCAPED_SECRET)
    assert_unrecoverable(repr(error.args), ESCAPED_SECRET)


def test_scrub_secret_values_leaves_unrelated_escapes_alone():
    """Only the secret's encodings are scrubbed, not every escape in the text."""
    from unifi_core.redaction import scrub_secret_values

    text = r"path C:\Users\admin rejected 'other\value'"

    assert scrub_secret_values(text, {ESCAPED_SECRET}) == text


def test_short_secret_still_masked_next_to_a_separator():
    """The default boundary rule treats ``-`` and ``_`` as separators, so a
    short secret beside one is still masked."""
    from unifi_core.redaction import REDACTED, scrub_secret_values

    assert scrub_secret_values("pin 123-foo and 123_bar", {"123"}) == f"pin {REDACTED}-foo and {REDACTED}_bar"


def test_sanitize_exception_marks_payload_values_with_the_guarded_marker():
    """A custom marker applies to free text only. Whole values under a
    sensitive key keep ``REDACTED``, which is the marker the write-back guards
    (``redaction_marker_paths``) recognise."""
    from unifi_core.redaction import REDACTED, sanitize_exception

    error = ValueError({"meta": {"msg": "rejected pw-one"}, "data": [{"x_password": "pw-one"}]})

    sanitize_exception(error, {"pw-one"}, marker="<redacted>")

    body = error.args[0]
    assert body["data"][0]["x_password"] == REDACTED
    assert body["meta"]["msg"] == "rejected <redacted>"


def test_scrub_is_linear_in_an_adversarial_secret():
    """The secret set comes from the caller's own payload, and the scrub runs
    synchronously inside the request path. Alternation branches of differing
    length must not let a failed match enumerate every composition."""
    import time

    from unifi_core.redaction import scrub_secret_values

    secret = "\\" * 20 + "Z"
    text = "controller rejected " + "\\" * 200 + " end"

    start = time.perf_counter()
    scrub_secret_values(text, {secret})

    assert time.perf_counter() - start < 1.0


def test_scrub_removes_a_login_that_prefixes_a_submitted_value():
    """Both are scrubbed in one pass, longest first. Masking the login first
    would chop the submitted value and leave its tail beside a mask the reader
    knows is the login."""
    from unifi_core.redaction import scrub_secret_values

    out = scrub_secret_values(
        "rejected {'x_password': 'admin@123'} for admin", {"admin@123": False, "admin": True}, marker="<redacted>"
    )

    assert "@123" not in out
    assert out == "rejected {'x_password': '<redacted>'} for <redacted>"


@pytest.mark.parametrize(
    ("secret", "build_text"),
    [
        # repr switches to single quotes when the value holds a double quote,
        # and then escapes the single ones.
        ("pw'quote\"both", lambda s: f"rejected {s!r}"),
        # A PHP- or Jackson-style encoder escapes the forward slash.
        ("pw/slash/value", lambda s: 'rejected "' + s.replace("/", "\\/") + '"'),
        # ascii() writes a non-ASCII character as \xNN, which neither repr nor
        # json.dumps produces.
        ("pw-ä-ascii-form", lambda s: f"rejected {ascii(s)}"),
        # A URL carries it percent-encoded, which is how aiohttp's
        # ClientResponseError renders the request it failed on.
        ('pw "space', lambda s: f"url='https://h/api?token={quote(s, safe='')}'"),
    ],
    ids=["repr_single_quote", "escaped_slash", "ascii_escape", "percent_encoded"],
)
def test_scrub_covers_each_character_form(secret, build_text):
    """Each rendering ``_char_forms`` enumerates needs its own case: without
    one, deleting that form from production leaves the suite green."""
    from unifi_core.redaction import scrub_secret_values

    assert_unrecoverable(scrub_secret_values(build_text(secret), {secret}), secret)


@pytest.mark.parametrize(
    ("secret", "text"),
    [
        ("p\\\\q", 'rejected {"x_password": "p\\\\q"}'),
        ("CORP\\admin", "login CORP\\admin failed"),
        ("a%25b", "pw=a%25b end"),
        ("\\\\", "pw=\\\\ end"),
    ],
    ids=["double_backslash_secret", "domain_login", "percent_literal", "backslash_run"],
)
def test_scrub_never_misses_the_literal_form(secret, text):
    """Whatever the encoded matching does, the value as written must always be
    found: a match that has to guess how many characters of the text one
    character of the secret occupies can guess wrong and leave it whole."""
    from unifi_core.redaction import scrub_secret_values

    assert secret not in scrub_secret_values(text, {secret})


def test_scrub_cost_stays_flat_as_an_adversarial_secret_grows():
    """Shape, not a wall-clock point: an ambiguous secret must not cost more as
    it lengthens, or a caller picks how long the event loop blocks."""
    import time

    from unifi_core.redaction import scrub_secret_values

    text = "controller rejected " + "\\" * 200 + " end"

    def _cost(length: int) -> float:
        secret = "\\" * length + "Z"
        start = time.perf_counter()
        scrub_secret_values(text, {secret})
        return time.perf_counter() - start

    short, long = _cost(12), _cost(24)

    assert long < max(short * 8, 0.05), f"cost grew from {short:.4f}s to {long:.4f}s"
