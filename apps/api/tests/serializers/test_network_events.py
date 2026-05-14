"""Network events cluster type unit tests.

Phase 6 PR2 Task 23 migrated the EVENT_LOG read shape (covering
``unifi_list_events``, ``unifi_get_alerts``, ``unifi_get_anomalies``,
``unifi_get_ips_events``) to a Strawberry ``EventLog`` type at
``unifi_api.graphql.types.network.event``. ``unifi_recent_events`` keeps
its serializer because the SSE stream generator calls ``serialize`` per
broadcast event.
"""

from unifi_api.graphql.types.network.event import EventLog


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
