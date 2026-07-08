"""Unit tests for the Network DynamicDns CRUD domain model."""

from __future__ import annotations

import pytest
from unifi_core.network.models.dynamic_dns import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    DynamicDns,
    from_controller,
    reject_unknown_fields,
    to_controller_create,
    to_controller_update,
)


class TestFieldSets:
    def test_mutable_fields_contains_expected(self) -> None:
        for field in (
            "host_name",
            "service",
            "server",
            "login",
            "x_password",
            "interface",
            "custom_service",
            "options",
        ):
            assert field in MUTABLE_FIELDS, f"Expected {field!r} in MUTABLE_FIELDS"

    def test_mutable_fields_excludes_read_only(self) -> None:
        assert "id" not in MUTABLE_FIELDS
        assert "site_id" not in MUTABLE_FIELDS

    def test_read_only_fields_contains_id_and_site_id(self) -> None:
        assert "id" in READ_ONLY_FIELDS
        assert "site_id" in READ_ONLY_FIELDS

    def test_mutable_and_read_only_are_disjoint(self) -> None:
        overlap = MUTABLE_FIELDS & READ_ONLY_FIELDS
        assert not overlap, f"Fields in both sets: {overlap}"

    def test_mutable_and_read_only_cover_all_model_fields(self) -> None:
        all_fields = frozenset(DynamicDns.model_fields.keys())
        assert MUTABLE_FIELDS | READ_ONLY_FIELDS == all_fields


class TestFromController:
    def test_full_dict(self) -> None:
        raw = {
            "_id": "ddns-1",
            "site_id": "site-1",
            "host_name": "home.example.com",
            "service": "dyndns",
            "server": "",
            "login": "user",
            "x_password": "secret-token",
            "interface": "wan",
        }
        r = from_controller(raw)
        assert r.id == "ddns-1"
        assert r.site_id == "site-1"
        assert r.host_name == "home.example.com"
        assert r.service == "dyndns"
        assert r.login == "user"
        assert r.interface == "wan"

    def test_id_coalesces_underscore_id(self) -> None:
        raw = {"_id": "abc", "host_name": "test.local", "service": "noip"}
        r = from_controller(raw)
        assert r.id == "abc"

    def test_secret_carried_raw(self) -> None:
        """from_controller carries the real secret; redaction happens at egress."""
        raw = {"_id": "r1", "x_password": "real-secret"}
        r = from_controller(raw)
        assert r.x_password == "real-secret"

    def test_options_list_carried(self) -> None:
        raw = {"_id": "r2", "options": ["opt1", "opt2"]}
        r = from_controller(raw)
        assert r.options == ["opt1", "opt2"]

    def test_handles_empty_dict(self) -> None:
        r = from_controller({})
        assert r.id is None
        assert r.host_name is None
        assert r.service is None


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

    def test_none_fields_excluded(self) -> None:
        model = DynamicDns(host_name="home.example.com", service="dyndns")
        payload = to_controller_create(model)
        assert "server" not in payload
        assert "login" not in payload
        assert "x_password" not in payload
        assert "custom_service" not in payload
        assert "options" not in payload

    def test_read_only_excluded(self) -> None:
        model = DynamicDns(id="should-not-appear", site_id="nope", host_name="home.example.com", service="dyndns")
        payload = to_controller_create(model)
        assert "id" not in payload
        assert "site_id" not in payload


class TestToControllerUpdate:
    def test_filters_out_read_only(self) -> None:
        result = to_controller_update({"id": "ignore", "site_id": "ignore", "service": "noip"})
        assert "id" not in result
        assert "site_id" not in result
        assert result["service"] == "noip"

    def test_drops_none_values(self) -> None:
        result = to_controller_update({"service": None, "host_name": "home.example.com"})
        assert "service" not in result
        assert result["host_name"] == "home.example.com"

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

    def test_returns_empty_dict_when_no_mutable_fields(self) -> None:
        result = to_controller_update({"id": "read-only"})
        assert result == {}


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
