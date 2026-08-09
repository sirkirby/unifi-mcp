"""Network events cluster type unit tests.

Phase 6 PR2 Task 23 migrated the EVENT_LOG read shape (covering
``unifi_list_events``, ``unifi_get_alerts``, ``unifi_get_anomalies``,
``unifi_get_ips_events``) to a Strawberry ``EventLog`` type at
``unifi_api.graphql.types.network.event``. ``unifi_recent_events`` keeps
its serializer because the SSE stream generator calls ``serialize`` per
broadcast event.
"""

from unifi_api.graphql.types.network.event import EventLog
from unifi_api.serializers.network.events import NetworkRecentEventsSerializer

# v2 /system-log/all record: actors nested under ``parameters`` by role,
# message shipped as a template. Exercises the delegated unifi-core mapping.
_V2_RECORD = {
    "id": "evt-0001",
    "key": "TRAFFIC_BLOCKED_KNOWN_SOURCE_CLIENT",
    "severity": "MEDIUM",
    "timestamp": 1786225096952,
    "message_raw": "{SRC_CLIENT} was blocked from accessing {DST_IP} by the {TRIGGER} Firewall Policy.",
    "parameters": {
        "SRC_CLIENT": {"id": "aa:bb:cc:00:00:01", "ip": "192.0.2.11", "name": "Lab-Camera"},
        "DST_IP": {"id": "198.51.100.24", "name": "198.51.100.24"},
        "TRIGGER": {"id": "trigger-0001", "name": "block cameras to external"},
    },
}

_V2_MSG = "Lab-Camera was blocked from accessing 198.51.100.24 by the block cameras to external Firewall Policy."


def test_event_log_serializer_basic_shape() -> None:
    sample = {
        "_id": "evt1",
        "key": "EVT_WU_Connected",
        "msg": "Client connected",
        "time": 1714000000000,
        "user": "aa:bb:cc:dd:ee:ff",
        "ip": "10.0.0.5",
    }
    item = EventLog.from_manager_output(sample).to_dict()
    hint = EventLog.render_hint("event_log")
    assert hint["kind"] == "event_log"
    assert hint["sort_default"] == "time:desc"
    assert item["id"] == "evt1"
    assert item["key"] == "EVT_WU_Connected"
    assert item["msg"] == "Client connected"
    assert item["time"] == 1714000000000
    assert item["mac"] == "aa:bb:cc:dd:ee:ff"
    assert item["ip"] == "10.0.0.5"
    assert "severity" not in item


def test_event_log_severity_passthrough() -> None:
    sample = {
        "_id": "a1",
        "key": "EVT_AD_Login",
        "msg": "x",
        "severity": "warn",
        "time": 100,
    }
    item = EventLog.from_manager_output(sample).to_dict()
    assert item["severity"] == "warn"
    assert item["id"] == "a1"


def test_event_log_non_dict_returns_id_none() -> None:
    item = EventLog.from_manager_output("not-a-dict").to_dict()
    assert item == {"id": None}


def test_event_log_v2_record_populates_mac_ip_and_msg() -> None:
    item = EventLog.from_manager_output(_V2_RECORD).to_dict()
    assert item["id"] == "evt-0001"
    assert item["mac"] == "aa:bb:cc:00:00:01"
    assert item["ip"] == "192.0.2.11"
    assert item["msg"] == _V2_MSG
    assert item["time"] == 1786225096952
    assert item["severity"] == "MEDIUM"


def test_event_log_v2_address_role_id_is_not_a_mac() -> None:
    """``DST_IP.id`` holds an IP string; it must never land in ``mac``."""
    record = {
        "key": "K",
        "message_raw": "{MYSTERY_ROLE} did something to {DST_IP}.",
        "parameters": {"DST_IP": {"id": "198.51.100.7", "name": "198.51.100.7"}},
    }
    item = EventLog.from_manager_output(record).to_dict()
    assert item["mac"] is None
    assert item["ip"] is None
    assert item["msg"] == "{MYSTERY_ROLE} did something to 198.51.100.7."


def test_event_log_legacy_keys_win_over_v2_parameters() -> None:
    record = {
        "key": "EVT_WU_Connected",
        "msg": "legacy message",
        "user": "aa:bb:cc:00:00:0a",
        "ip": "192.0.2.60",
        "message_raw": "{SRC_CLIENT} connected.",
        "parameters": {"SRC_CLIENT": {"id": "aa:bb:cc:00:00:0b", "ip": "192.0.2.61"}},
    }
    item = EventLog.from_manager_output(record).to_dict()
    assert item["mac"] == "aa:bb:cc:00:00:0a"
    assert item["ip"] == "192.0.2.60"
    assert item["msg"] == "legacy message"


def test_recent_events_serializer_v2_record() -> None:
    out = NetworkRecentEventsSerializer.serialize(_V2_RECORD)
    assert out["mac"] == "aa:bb:cc:00:00:01"
    assert out["ip"] == "192.0.2.11"
    assert out["msg"] == _V2_MSG
    assert out["severity"] == "MEDIUM"


def test_recent_events_serializer_legacy_contract_preserved() -> None:
    out = NetworkRecentEventsSerializer.serialize(
        {
            "_id": "legacy-1",
            "key": "EVT_WU_Disconnected",
            "msg": "Client disconnected",
            "time": 1700000000000,
            "user": "aa:bb:cc:00:00:09",
            "ip": "192.0.2.50",
        }
    )
    assert out["id"] == "legacy-1"
    assert out["mac"] == "aa:bb:cc:00:00:09"
    assert out["msg"] == "Client disconnected"
    assert "severity" not in out
    assert NetworkRecentEventsSerializer.serialize("not-a-dict") == {"id": None}
