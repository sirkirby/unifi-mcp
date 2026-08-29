"""EventBuffer tests for network EventManager."""

import time

from unifi_core.network.managers.event_manager import EventBuffer


def test_buffer_add_and_get_recent() -> None:
    buf = EventBuffer(max_size=10, ttl_seconds=300)
    buf.add({"id": "e1", "key": "EVT_LU_Connected", "msg": "client connected"})
    buf.add({"id": "e2", "key": "EVT_LU_Disconnected", "msg": "client disconnected"})
    out = buf.get_recent()
    assert len(out) == 2
    assert {e["id"] for e in out} == {"e1", "e2"}


def test_buffer_ttl_filters_stale() -> None:
    buf = EventBuffer(max_size=10, ttl_seconds=1)
    buf.add({"id": "old"})
    time.sleep(1.1)
    buf.add({"id": "new"})
    out = buf.get_recent()
    assert [e["id"] for e in out] == ["new"]


def test_buffer_max_size_evicts_oldest() -> None:
    buf = EventBuffer(max_size=3, ttl_seconds=300)
    for i in range(5):
        buf.add({"id": f"e{i}"})
    out = buf.get_recent()
    assert len(out) == 3
    assert {e["id"] for e in out} == {"e2", "e3", "e4"}


def test_buffer_filter_by_event_type() -> None:
    buf = EventBuffer(max_size=10, ttl_seconds=300)
    buf.add({"id": "e1", "key": "EVT_LU_Connected"})
    buf.add({"id": "e2", "key": "EVT_LU_Disconnected"})
    buf.add({"id": "e3", "key": "EVT_LU_Connected"})
    out = buf.get_recent(event_type="EVT_LU_Connected")
    assert {e["id"] for e in out} == {"e1", "e3"}


def test_buffer_event_type_filter_requires_exact_key() -> None:
    buf = EventBuffer(max_size=10, ttl_seconds=300)
    buf.add({"id": "e1", "key": "CLIENT_CONNECTED_WIRELESS_2"})

    assert buf.get_recent(event_type="CLIENT_CONNECTED") == []


def test_buffer_clear() -> None:
    buf = EventBuffer(max_size=10, ttl_seconds=300)
    buf.add({"id": "e1"})
    buf.clear()
    assert buf.get_recent() == []
    assert len(buf) == 0
