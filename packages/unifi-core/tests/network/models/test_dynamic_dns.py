"""Unit tests for the Network DynamicDns CRUD domain model."""

from __future__ import annotations

import pytest
from unifi_core.network.models.dynamic_dns import (
    DynamicDns,
    from_controller,
    reject_unknown_fields,
    to_controller_create,
    to_controller_update,
)

from .model_assertions import assert_fields


class TestFromController:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (
                {
                    "_id": "ddns-1",
                    "site_id": "site-1",
                    "host_name": "home.example.com",
                    "service": "dyndns",
                    "server": "",
                    "login": "user",
                    "x_password": "secret-token",
                    "interface": "wan",
                },
                {
                    "id": "ddns-1",
                    "site_id": "site-1",
                    "host_name": "home.example.com",
                    "service": "dyndns",
                    "login": "user",
                    "interface": "wan",
                },
            ),
            ({"_id": "abc", "host_name": "test.local", "service": "noip"}, {"id": "abc"}),
            ({"_id": "r2", "options": ["opt1", "opt2"]}, {"options": ["opt1", "opt2"]}),
            ({}, {"id": None, "host_name": None, "service": None}),
        ],
        ids=["full_dict", "id_coalesces_underscore_id", "options_list_carried", "handles_empty_dict"],
    )
    def test_from_controller_fields(self, raw, expected) -> None:
        result = from_controller(raw)
        assert_fields(result, expected)

    def test_secret_carried_raw(self) -> None:
        """from_controller carries the real secret; redaction happens at egress."""
        raw = {"_id": "r1", "x_password": "real-secret"}
        r = from_controller(raw)
        assert r.x_password == "real-secret"


class TestToControllerCreate:
    def test_full_model(self) -> None:
        model = DynamicDns(
            host_name="home.example.com",
            service="dyndns",
            login="user",
            x_password="secret",
            interface="wan",
        )
        payload = to_controller_create(model)
        assert payload["host_name"] == "home.example.com"
        assert payload["service"] == "dyndns"
        assert payload["login"] == "user"
        assert payload["x_password"] == "secret"
        assert payload["interface"] == "wan"


class TestToControllerUpdate:
    def test_passes_all_mutable_fields(self) -> None:
        fields = {
            "host_name": "home.example.com",
            "service": "custom",
            "server": "update.example.com",
            "login": "user",
            "x_password": "secret",
            "interface": "wan2",
            "custom_service": "custom",
            "options": ["a", "b"],
        }
        result = to_controller_update(fields)
        assert result == fields


class TestRejectUnknownFields:
    """The create/update flow rejects unknown or read-only keys with an
    actionable error rather than silently dropping them (maintainer request:
    do not reintroduce the silent-drop class the strict-kwargs protections
    were added to avoid)."""

    def test_passes_when_all_keys_mutable(self) -> None:
        # No exception for a dict of accepted fields.
        reject_unknown_fields({"host_name": "home.example.com", "service": "noip"})

    def test_passes_on_empty(self) -> None:
        reject_unknown_fields({})

    def test_rejects_unrecognised_key(self) -> None:
        with pytest.raises(ValueError) as exc:
            reject_unknown_fields({"service": "noip", "bogus_field": "x"})
        assert "bogus_field" in str(exc.value)
        # The message is actionable — it names the allowed fields.
        assert "host_name" in str(exc.value)

    def test_rejects_read_only_key(self) -> None:
        with pytest.raises(ValueError) as exc:
            reject_unknown_fields({"id": "read-only", "service": "noip"})
        assert "id" in str(exc.value)
