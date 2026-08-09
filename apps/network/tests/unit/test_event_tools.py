"""Tests for event/alarm tool confirmation previews."""

import os

import pytest

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")


@pytest.mark.asyncio
async def test_archive_alarm_preview_requires_confirmation():
    from unifi_network_mcp.tools.events import archive_alarm

    result = await archive_alarm(alarm_id="alarm123", confirm=False)

    assert result["success"] is True
    assert result["requires_confirmation"] is True
    assert result["resource_type"] == "alarm"
    assert result["resource_id"] == "alarm123"
    assert result["preview"]["proposed"]["archived"] is True


@pytest.mark.asyncio
async def test_archive_all_alarms_preview_requires_confirmation():
    from unifi_network_mcp.tools.events import archive_all_alarms

    result = await archive_all_alarms(confirm=False)

    assert result["success"] is True
    assert result["requires_confirmation"] is True
    assert result["resource_type"] == "alarm_collection"
    assert result["resource_id"] == "all_active_alarms"
    assert result["preview"]["proposed"]["archived"] is True


class _StubConnection:
    site = "default"


class _StubEventManager:
    """Minimal stand-in for EventManager returning canned records."""

    _connection = _StubConnection()

    def __init__(self, records):
        self._records = records

    async def get_events(self, **_kwargs):
        return self._records


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


@pytest.mark.asyncio
async def test_list_events_surfaces_mac_ip_and_msg_for_v2_records(monkeypatch):
    """End-to-end through the tool: v2 records must not come back anonymous.

    ``model_dump(exclude_none=True)`` drops unresolved fields, so a mapping
    gap shows up as missing keys rather than nulls.
    """
    from unifi_network_mcp.tools import events as events_module

    monkeypatch.setattr(
        events_module,
        "_get_event_manager",
        lambda: _StubEventManager([_V2_RECORD]),
    )

    result = await events_module.list_events(within_hours=1, limit=10)

    assert result["success"] is True
    assert result["count"] == 1
    event = result["events"][0]
    assert event["mac"] == "aa:bb:cc:00:00:01"
    assert event["ip"] == "192.0.2.11"
    assert event["msg"] == (
        "Lab-Camera was blocked from accessing 198.51.100.24 by the block cameras to external Firewall Policy."
    )


@pytest.mark.asyncio
async def test_list_events_still_maps_legacy_records(monkeypatch):
    from unifi_network_mcp.tools import events as events_module

    legacy = {
        "_id": "legacy-1",
        "key": "EVT_WU_Disconnected",
        "msg": "Client disconnected",
        "time": 1700000000000,
        "user": "aa:bb:cc:00:00:09",
        "ip": "192.0.2.50",
    }
    monkeypatch.setattr(
        events_module,
        "_get_event_manager",
        lambda: _StubEventManager([legacy]),
    )

    event = (await events_module.list_events())["events"][0]

    assert event["mac"] == "aa:bb:cc:00:00:09"
    assert event["ip"] == "192.0.2.50"
    assert event["msg"] == "Client disconnected"
