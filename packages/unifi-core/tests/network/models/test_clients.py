"""Unit tests for the Network Client / BlockedClient / ClientLookup models.

Covers the four-cell matrix for the (hostname, name) pair so that the
user-assigned alias is preserved alongside the DHCP-reported hostname.
"""

from __future__ import annotations

from unifi_core.network.models.clients import (
    BLOCKEDCLIENT_READ_ONLY_FIELDS,
    CLIENT_MUTABLE_FIELDS,
    CLIENT_READ_ONLY_FIELDS,
    CLIENTLOOKUP_READ_ONLY_FIELDS,
    Client,
    blocked_client_from_controller,
    client_from_controller,
    client_lookup_from_controller,
)


class TestClientFieldSets:
    def test_no_mutable_fields(self) -> None:
        assert CLIENT_MUTABLE_FIELDS == frozenset()

    def test_read_only_covers_all_fields(self) -> None:
        all_fields = frozenset(Client.model_fields.keys())
        assert CLIENT_READ_ONLY_FIELDS == all_fields

    def test_name_field_is_part_of_schema(self) -> None:
        assert "name" in Client.model_fields
        assert "hostname" in Client.model_fields


class TestClientFromController:
    def test_both_set_distinct(self) -> None:
        c = client_from_controller({"mac": "aa:bb:cc:dd:ee:ff", "hostname": "RingHpCam-c0", "name": "RingCam-Driveway"})
        assert c.hostname == "RingHpCam-c0"
        assert c.name == "RingCam-Driveway"

    def test_both_set_equal(self) -> None:
        c = client_from_controller({"mac": "aa:bb:cc:dd:ee:ff", "hostname": "same", "name": "same"})
        assert c.hostname == "same"
        assert c.name == "same"

    def test_name_only(self) -> None:
        c = client_from_controller({"mac": "aa:bb:cc:dd:ee:ff", "name": "Office Apple TV"})
        assert c.hostname is None
        assert c.name == "Office Apple TV"

    def test_hostname_only(self) -> None:
        c = client_from_controller({"mac": "aa:bb:cc:dd:ee:ff", "hostname": "Office-TV-3"})
        assert c.hostname == "Office-TV-3"
        assert c.name is None

    def test_neither_set(self) -> None:
        c = client_from_controller({"mac": "aa:bb:cc:dd:ee:ff"})
        assert c.hostname is None
        assert c.name is None

    def test_empty_strings_normalize_to_none(self) -> None:
        c = client_from_controller({"mac": "aa:bb:cc:dd:ee:ff", "hostname": "", "name": ""})
        assert c.hostname is None
        assert c.name is None


class TestBlockedClientFromController:
    def test_both_set_distinct(self) -> None:
        c = blocked_client_from_controller(
            {"mac": "aa:bb:cc:dd:ee:ff", "hostname": "HarmonyHub", "name": "Living Room Harmony"}
        )
        assert c.hostname == "HarmonyHub"
        assert c.name == "Living Room Harmony"

    def test_name_only(self) -> None:
        c = blocked_client_from_controller({"mac": "aa:bb:cc:dd:ee:ff", "name": "Living Room Harmony"})
        assert c.hostname is None
        assert c.name == "Living Room Harmony"

    def test_hostname_only(self) -> None:
        c = blocked_client_from_controller({"mac": "aa:bb:cc:dd:ee:ff", "hostname": "HarmonyHub"})
        assert c.hostname == "HarmonyHub"
        assert c.name is None

    def test_read_only_covers_name(self) -> None:
        assert "name" in BLOCKEDCLIENT_READ_ONLY_FIELDS


class TestClientLookupFromController:
    def test_both_set_distinct(self) -> None:
        c = client_lookup_from_controller(
            {
                "mac": "aa:bb:cc:dd:ee:ff",
                "ip": "10.0.0.5",
                "hostname": "Elgato Key Light 1C09",
                "name": "Office Key Light Right",
                "is_online": True,
            }
        )
        assert c.hostname == "Elgato Key Light 1C09"
        assert c.name == "Office Key Light Right"
        assert c.is_online is True

    def test_name_only(self) -> None:
        c = client_lookup_from_controller({"mac": "aa:bb:cc:dd:ee:ff", "name": "Office Key Light"})
        assert c.hostname is None
        assert c.name == "Office Key Light"

    def test_hostname_only(self) -> None:
        c = client_lookup_from_controller({"mac": "aa:bb:cc:dd:ee:ff", "hostname": "Elgato Key Light"})
        assert c.hostname == "Elgato Key Light"
        assert c.name is None

    def test_read_only_covers_name(self) -> None:
        assert "name" in CLIENTLOOKUP_READ_ONLY_FIELDS
