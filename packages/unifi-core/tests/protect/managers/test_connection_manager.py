"""Tests for ProtectConnectionManager public API guardrails."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from unifi_core.protect.managers.connection_manager import ProtectConnectionManager
from unifi_core.protect.managers.sensor_manager import SensorManager


def _make_connection_manager(api_key: str | None = None) -> ProtectConnectionManager:
    return ProtectConnectionManager(
        host="protect.example.test",
        username="admin",
        password="secret",
        api_key=api_key,
    )


@pytest.mark.parametrize(
    ("api_key", "expected"),
    [
        ("protect-api-key", True),
        (None, False),
        ("", False),
        ("   ", False),
    ],
)
def test_has_api_key_is_true_only_when_api_key_is_configured(api_key: str | None, expected: bool) -> None:
    cm = _make_connection_manager(api_key=api_key)

    assert cm.has_api_key is expected


def test_require_public_api_key_returns_cleanly_when_configured() -> None:
    cm = _make_connection_manager(api_key="protect-api-key")

    cm.require_public_api_key("update sensor settings")


def test_require_public_api_key_raises_actionable_error_when_missing() -> None:
    cm = _make_connection_manager()

    with pytest.raises(ValueError) as exc_info:
        cm.require_public_api_key("update sensor settings")

    message = str(exc_info.value)
    assert "update sensor settings" in message
    assert "UNIFI_PROTECT_API_KEY" in message
    assert "UNIFI_API_KEY" in message


@pytest.mark.asyncio
async def test_manager_bootstrap_ids_can_be_compared_to_public_ids_without_tool_layer() -> None:
    sensor_id = "sensor-abc"
    sensor = SimpleNamespace(
        id=sensor_id,
        name="Entry Sensor",
        type="sensor",
        market_name="Protect Sensor",
        state=None,
        is_connected=True,
        firmware_version="1.0.0",
        last_seen=None,
        mount_type=None,
        is_motion_detected=False,
        is_opened=False,
        motion_detected_at=None,
        open_status_changed_at=None,
        alarm_triggered_at=None,
        leak_detected_at=None,
        tampering_detected_at=None,
        battery_status=None,
        stats=None,
        camera_id=None,
    )
    client = SimpleNamespace(
        bootstrap=SimpleNamespace(sensors={sensor_id: sensor}),
        get_sensors_public=AsyncMock(return_value=[{"id": sensor_id, "name": "Entry Sensor"}]),
    )
    manager = SensorManager(SimpleNamespace(client=client))

    bootstrap_ids = {item["id"] for item in await manager.list_sensors()}
    public_ids = {item["id"] for item in await client.get_sensors_public()}

    assert bootstrap_ids == public_ids == {sensor_id}
