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
    _is_online,
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


class TestIsOnlineDerivation:
    """Online-status derivation must survive controller firmwares that omit
    `is_online` from /stat/sta payloads but populate active-connection
    indicators (`_uptime_by_*`, `uptime`).
    """

    def test_is_online_true_explicit(self) -> None:
        assert _is_online({"is_online": True}) is True

    def test_is_online_false_explicit_no_uptime(self) -> None:
        assert _is_online({"is_online": False}) is False

    def test_is_online_missing_no_uptime(self) -> None:
        assert _is_online({}) is False

    def test_uptime_by_uap_positive(self) -> None:
        assert _is_online({"_uptime_by_uap": 42}) is True

    def test_uptime_by_usw_positive(self) -> None:
        assert _is_online({"_uptime_by_usw": 1}) is True

    def test_uptime_by_ugw_positive(self) -> None:
        assert _is_online({"_uptime_by_ugw": 1}) is True

    def test_plain_uptime_positive(self) -> None:
        assert _is_online({"uptime": 1}) is True

    def test_uptime_zero_is_offline(self) -> None:
        assert _is_online({"_uptime_by_uap": 0, "uptime": 0}) is False

    def test_uptime_non_numeric_is_ignored(self) -> None:
        assert _is_online({"_uptime_by_uap": "yes"}) is False

    def test_stat_sta_shape_without_is_online_field(self) -> None:
        """Fixture mirrors the shape of /stat/sta records from controller
        firmwares that omit `is_online` (UniFi OS 5.x / Network 10.x):
        rich active indicators (uptime, signal, essid) but no explicit
        `is_online` field. Must derive as online.
        """
        raw = {
            "mac": "aa:bb:cc:dd:ee:ff",
            "hostname": "wireless-speaker",
            "name": "Living Room Speaker",
            "uptime": 3639515,
            "_uptime_by_uap": 3639515,
            "_uptime_by_usw": 135036,
            "_uptime_by_ugw": 135036,
            "signal": -52,
            "channel": 11,
            "radio": "ng",
            "essid": "TestMesh-IoT",
        }
        assert _is_online(raw) is True
        c = client_from_controller(raw)
        assert c.status == "online"
        assert c.name == "Living Room Speaker"
        assert c.hostname == "wireless-speaker"

    def test_client_lookup_derives_online_from_uptime(self) -> None:
        lookup = client_lookup_from_controller({"mac": "aa:bb", "ip": "10.0.0.5", "uptime": 99})
        assert lookup.is_online is True

    def test_client_lookup_offline_when_no_indicators(self) -> None:
        lookup = client_lookup_from_controller({"mac": "aa:bb", "ip": "10.0.0.5"})
        assert lookup.is_online is False

    def test_client_lookup_flat_attribute_object_with_is_online_true(self) -> None:
        """`client_lookup_from_controller` accepts objects without a `.raw`
        attribute — the is_online derivation must use the same access
        semantics as peer fields (mac, ip, hostname) on the same factory.
        """

        class FlatClient:
            mac = "aa:bb:cc:dd:ee:ff"
            ip = "10.0.0.5"
            hostname = "host"
            name = "Alias"
            is_online = True
            last_seen = None

        lookup = client_lookup_from_controller(FlatClient())
        assert lookup.is_online is True
        assert lookup.mac == "aa:bb:cc:dd:ee:ff"

    def test_client_lookup_flat_attribute_object_with_uptime(self) -> None:
        class FlatClient:
            mac = "aa:bb:cc:dd:ee:ff"
            ip = "10.0.0.5"
            hostname = "host"
            name = None
            _uptime_by_uap = 99
            is_online = None
            last_seen = None

        lookup = client_lookup_from_controller(FlatClient())
        assert lookup.is_online is True
