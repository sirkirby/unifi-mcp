"""Unit tests for the Access device-config read/update domain helpers."""

from __future__ import annotations

from unifi_core.access.models.device_configs import (
    build_config_write_body,
    from_controller,
    is_camera_device_id,
    is_sensitive_config,
    redact_config_entries,
    validate_config_updates,
)
from unifi_core.redaction import REDACTED


class TestFromController:
    def test_full_dict(self) -> None:
        # The controller returns update_time/create_time as ISO 8601 strings,
        # not epoch ints (verified live against a UNVR).
        raw = {
            "device_id": "dev-1",
            "key": "show_entry_greet",
            "value": "yes",
            "tag": "device_setting",
            "update_time": "2026-04-03T12:17:26-07:00",
            "create_time": "2026-04-01T09:00:00-07:00",
        }
        entry = from_controller(raw)
        assert entry.device_id == "dev-1"
        assert entry.key == "show_entry_greet"
        assert entry.value == "yes"
        assert entry.tag == "device_setting"
        assert entry.update_time == "2026-04-03T12:17:26-07:00"
        assert entry.create_time == "2026-04-01T09:00:00-07:00"

    def test_iso_string_timestamps_do_not_raise(self) -> None:
        # Regression: the controller sends ISO-8601 timestamp strings; the model
        # must carry them verbatim, not reject them as non-int (bug caught by
        # live MCP QA — apps/api masked it because Strawberry assigns loosely).
        entry = from_controller({"key": "k", "update_time": "2026-04-03T12:17:26-07:00"})
        assert entry.update_time == "2026-04-03T12:17:26-07:00"

    def test_handles_empty_dict(self) -> None:
        entry = from_controller({})
        assert entry.key is None
        assert entry.value is None
        assert entry.tag is None

    def test_handles_partial_dict(self) -> None:
        entry = from_controller({"key": "greeting_text", "value": "welcome"})
        assert entry.key == "greeting_text"
        assert entry.value == "welcome"
        assert entry.tag is None

    def test_accepts_object_with_attributes(self) -> None:
        class Obj:
            device_id = "dev-2"
            key = "greeting_broadcast_name"
            value = "first_name_only"
            tag = "device_setting"
            update_time = None
            create_time = None

        entry = from_controller(Obj())
        assert entry.device_id == "dev-2"
        assert entry.key == "greeting_broadcast_name"
        assert entry.value == "first_name_only"

    def test_carries_secret_value_verbatim(self) -> None:
        # The domain model is lossless: redaction is a response-boundary concern,
        # not the model's job (mirrors the Credential model).
        entry = from_controller({"key": "ssh_password", "value": "hunter2", "tag": "credential"})
        assert entry.value == "hunter2"


class TestIsSensitiveConfig:
    def test_credential_tag_is_sensitive_regardless_of_key(self) -> None:
        assert is_sensitive_config("some_opaque_key", "credential") is True

    def test_sensitive_key_name_is_sensitive_even_without_credential_tag(self) -> None:
        # ssh_password carries "password" segment; nacl_private_key carries the
        # private-key qualifier — both must trip is_sensitive_key.
        assert is_sensitive_config("ssh_password", "device_setting") is True
        assert is_sensitive_config("nacl_private_key", "device_extra") is True

    def test_ordinary_device_setting_is_not_sensitive(self) -> None:
        assert is_sensitive_config("show_entry_greet", "device_setting") is False
        assert is_sensitive_config("greeting_text", "device_setting") is False

    def test_none_key_and_tag(self) -> None:
        assert is_sensitive_config(None, None) is False


class TestRedactConfigEntries:
    def _entries(self) -> list[dict]:
        return [
            {"device_id": "d1", "key": "show_entry_greet", "value": "yes", "tag": "device_setting"},
            {"device_id": "d1", "key": "ssh_password", "value": "hunter2", "tag": "credential"},
            {"device_id": "d1", "key": "nacl_private_key", "value": "AbCd==", "tag": "device_extra"},
        ]

    def test_redacts_credential_tagged_value(self) -> None:
        out = redact_config_entries(self._entries(), redact_sensitive=True)
        cred = next(e for e in out if e["key"] == "ssh_password")
        assert cred["value"] == REDACTED

    def test_redacts_sensitive_key_value_even_without_credential_tag(self) -> None:
        out = redact_config_entries(self._entries(), redact_sensitive=True)
        priv = next(e for e in out if e["key"] == "nacl_private_key")
        assert priv["value"] == REDACTED

    def test_leaves_ordinary_value_untouched(self) -> None:
        out = redact_config_entries(self._entries(), redact_sensitive=True)
        greet = next(e for e in out if e["key"] == "show_entry_greet")
        assert greet["value"] == "yes"

    def test_preserves_non_value_fields(self) -> None:
        out = redact_config_entries(self._entries(), redact_sensitive=True)
        cred = next(e for e in out if e["key"] == "ssh_password")
        assert cred["device_id"] == "d1"
        assert cred["tag"] == "credential"
        assert cred["key"] == "ssh_password"

    def test_redact_disabled_returns_values_unchanged(self) -> None:
        out = redact_config_entries(self._entries(), redact_sensitive=False)
        cred = next(e for e in out if e["key"] == "ssh_password")
        assert cred["value"] == "hunter2"

    def test_none_value_is_not_replaced_with_marker(self) -> None:
        out = redact_config_entries(
            [{"device_id": "d1", "key": "ssh_password", "value": None, "tag": "credential"}],
            redact_sensitive=True,
        )
        assert out[0]["value"] is None

    def test_does_not_mutate_input(self) -> None:
        entries = self._entries()
        redact_config_entries(entries, redact_sensitive=True)
        cred = next(e for e in entries if e["key"] == "ssh_password")
        assert cred["value"] == "hunter2"


class TestIsCameraDeviceId:
    def test_protect_style_24_hex_is_camera(self) -> None:
        # G6 Pro Entry / camera-class readers carry a 24-hex Protect-style id.
        assert is_camera_device_id("a1b2c3d4e5f607182930abcd") is True

    def test_mac_style_12_hex_is_not_camera(self) -> None:
        # Hubs use a MAC-style (12-hex) id.
        assert is_camera_device_id("aabbccddeeff") is False

    def test_mac_with_colons_is_not_camera(self) -> None:
        assert is_camera_device_id("1C:0B:8B:EE:F6:B5") is False

    def test_empty_or_none_is_not_camera(self) -> None:
        assert is_camera_device_id("") is False
        assert is_camera_device_id(None) is False


class TestValidateConfigUpdates:
    def _current(self) -> dict:
        return {
            "show_entry_greet": {"key": "show_entry_greet", "value": "yes", "tag": "device_setting"},
            "greeting_text": {"key": "greeting_text", "value": "welcome", "tag": "device_setting"},
            "ssh_password": {"key": "ssh_password", "value": "hunter2", "tag": "credential"},
        }

    def test_valid_update_passes(self) -> None:
        ok, err = validate_config_updates({"show_entry_greet": "no"}, self._current())
        assert ok is True
        assert err is None

    def test_empty_updates_rejected(self) -> None:
        ok, err = validate_config_updates({}, self._current())
        assert ok is False
        assert err

    def test_unknown_key_rejected_and_lists_allowed(self) -> None:
        ok, err = validate_config_updates({"not_a_real_key": "x"}, self._current())
        assert ok is False
        assert "not_a_real_key" in err
        # error should surface the legitimately-writable keys
        assert "show_entry_greet" in err

    def test_credential_tagged_key_rejected(self) -> None:
        ok, err = validate_config_updates({"ssh_password": "newpass"}, self._current())
        assert ok is False
        assert "ssh_password" in err

    def test_sensitive_key_name_rejected(self) -> None:
        current = {"api_token": {"key": "api_token", "value": "t", "tag": "device_setting"}}
        ok, err = validate_config_updates({"api_token": "new"}, current)
        assert ok is False
        assert "api_token" in err


class TestBuildConfigWriteBody:
    def _current(self) -> dict:
        return {
            "show_entry_greet": {"key": "show_entry_greet", "value": "yes", "tag": "device_setting"},
            "greeting_text": {"key": "greeting_text", "value": "welcome", "tag": "device_setting"},
        }

    def test_builds_key_tag_value_array(self) -> None:
        body = build_config_write_body({"show_entry_greet": "no"}, self._current())
        assert body == [{"key": "show_entry_greet", "tag": "device_setting", "value": "no"}]

    def test_coerces_value_to_string(self) -> None:
        body = build_config_write_body({"show_entry_greet": False}, self._current())
        assert body[0]["value"] == "False"

    def test_partial_update_single_entry(self) -> None:
        body = build_config_write_body({"greeting_text": "hello"}, self._current())
        assert len(body) == 1
        assert body[0]["key"] == "greeting_text"
        assert body[0]["tag"] == "device_setting"
        assert body[0]["value"] == "hello"
