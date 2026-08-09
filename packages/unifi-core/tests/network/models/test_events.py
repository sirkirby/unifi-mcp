"""Tests for Network EventLog model + serializer.

Covers both controller shapes:
- legacy ``/stat/event`` (flat ``user``/``msg``/``ip`` keys)
- v2 ``/system-log/all`` (nested ``parameters`` + ``message_raw`` template)
"""

import json
from pathlib import Path

from unifi_core.network.models.events import (
    MUTABLE_FIELDS,
    EventLog,
    event_log_from_controller,
)

# package-local fixture: models -> network (parents[1]) -> fixtures/
_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "system_log_events_response.json"


def _records():
    return json.loads(_FIXTURE.read_text())["data"]


def _by_key(key: str):
    return next(r for r in _records() if r["key"] == key)


# ---------------------------------------------------------------------------
# v2 /system-log/all
# ---------------------------------------------------------------------------


def test_v2_firewall_event_populates_mac_ip_and_message():
    event = event_log_from_controller(_by_key("TRAFFIC_BLOCKED_KNOWN_SOURCE_CLIENT"))

    assert event.id == "evt-0001"
    assert event.key == "TRAFFIC_BLOCKED_KNOWN_SOURCE_CLIENT"
    assert event.severity == "MEDIUM"
    assert event.time == 1786225096952
    assert event.mac == "aa:bb:cc:00:00:01"
    assert event.ip == "192.0.2.11"
    assert event.msg == (
        "Lab-Camera was blocked from accessing 198.51.100.24 by the block cameras to external Firewall Policy."
    )


def test_v2_threat_event_prefers_src_client_over_device():
    """DEVICE is the reporting console, not the offender — SRC_CLIENT wins."""
    event = event_log_from_controller(_by_key("THREAT_DETECTED_KNOWN_SOURCE_CLIENT"))

    assert event.mac == "aa:bb:cc:00:00:02"
    assert event.msg == ("A network intrusion attempt from Lab-Host to 198.51.100.99 has been detected.")


def test_v2_mac_and_ip_always_describe_the_same_actor():
    """SRC_CLIENT (the offender) has no ip; DEVICE (the console) has 192.0.2.1.

    Reading the two fields independently would report the offender's MAC
    alongside the gateway's IP, which reads as a single device and is wrong.
    """
    event = event_log_from_controller(_by_key("THREAT_DETECTED_KNOWN_SOURCE_CLIENT"))

    assert event.mac == "aa:bb:cc:00:00:02"
    assert event.ip is None


def test_v2_ip_falls_back_across_actors_only_without_a_mac():
    record = {
        "key": "K",
        "parameters": {"DEVICE": {"id": "console-name-not-a-mac", "ip": "192.0.2.1"}},
    }
    event = event_log_from_controller(record)

    assert event.mac is None
    assert event.ip == "192.0.2.1"


def test_v2_client_event_uses_client_role():
    event = event_log_from_controller(_by_key("CLIENT_CONNECTED_WIRELESS_2"))

    assert event.mac == "aa:bb:cc:00:00:03"
    assert event.msg == "Lab-Phone has connected to Lab-AP."


def test_v2_address_role_id_is_not_mistaken_for_a_mac():
    """``DST_IP.id`` is an IP string; it must never land in ``mac``."""
    event = event_log_from_controller(_by_key("EVENT_WITH_UNKNOWN_PLACEHOLDER"))

    assert event.mac is None
    assert event.ip is None


def test_v2_unknown_placeholder_is_left_intact():
    event = event_log_from_controller(_by_key("EVENT_WITH_UNKNOWN_PLACEHOLDER"))

    assert event.msg == "{MYSTERY_ROLE} did something to 198.51.100.7."


def test_v2_falls_back_to_title_when_no_template():
    event = event_log_from_controller({"id": "e", "key": "K", "title_raw": "Threat Detected", "timestamp": 1})

    assert event.msg == "Threat Detected"


def test_every_fixture_record_yields_a_message():
    for record in _records():
        assert event_log_from_controller(record).msg, record["key"]


# ---------------------------------------------------------------------------
# legacy /stat/event — must be unaffected
# ---------------------------------------------------------------------------


def test_legacy_flat_shape_still_maps():
    event = event_log_from_controller(
        {
            "_id": "legacy-1",
            "key": "EVT_WU_Disconnected",
            "msg": "Client disconnected",
            "time": 1700000000000,
            "user": "aa:bb:cc:00:00:09",
            "ip": "192.0.2.50",
        }
    )

    assert event.id == "legacy-1"
    assert event.mac == "aa:bb:cc:00:00:09"
    assert event.ip == "192.0.2.50"
    assert event.msg == "Client disconnected"


def test_legacy_keys_win_over_v2_parameters():
    event = event_log_from_controller(
        {
            "key": "EVT_WU_Connected",
            "msg": "legacy message",
            "user": "aa:bb:cc:00:00:0a",
            "ip": "192.0.2.60",
            "message_raw": "{SRC_CLIENT} connected.",
            "parameters": {"SRC_CLIENT": {"id": "aa:bb:cc:00:00:0b", "ip": "192.0.2.61"}},
        }
    )

    assert event.mac == "aa:bb:cc:00:00:0a"
    assert event.ip == "192.0.2.60"
    assert event.msg == "legacy message"


def test_ap_mac_fallback_preserved():
    event = event_log_from_controller({"key": "EVT_AP_Lost_Contact", "ap": "aa:bb:cc:00:00:0c"})

    assert event.mac == "aa:bb:cc:00:00:0c"


# ---------------------------------------------------------------------------
# defensive
# ---------------------------------------------------------------------------


def test_non_dict_record_yields_empty_model():
    for value in (None, [], "event", 7):
        assert event_log_from_controller(value) == EventLog()


def test_malformed_parameters_are_ignored():
    for params in ("not-a-dict", [], None, {"SRC_CLIENT": "not-a-dict"}):
        event = event_log_from_controller({"key": "K", "parameters": params})
        assert event.mac is None
        assert event.ip is None


def test_eventlog_fields_marked_immutable():
    assert MUTABLE_FIELDS == frozenset()
    for field in EventLog.model_fields.values():
        assert (field.json_schema_extra or {}).get("mutable") is False
