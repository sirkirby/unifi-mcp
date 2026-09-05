"""Tests for the Protect support-bundle adapter."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from unifi_core.support_bundle import connection_attempt_succeeded, connectivity_probe_result
from unifi_protect_mcp.support import ProtectSupportBundleAdapter


def _manager(*, connected: bool = True):
    return SimpleNamespace(
        support_status=lambda: {
            "initialized": connected,
            "connected": connected,
            "tls_verification_enabled": True,
            "last_attempt": connection_attempt_succeeded(),
            "session_available": connected,
            "bootstrap_available": connected,
            "public_api_key_configured": True,
            "websocket_state": "connected" if connected else "unknown",
        },
        support_connectivity_probe=AsyncMock(return_value=connectivity_probe_result("timeout", 10_000)),
    )


async def test_protect_summary_reports_typed_cached_capabilities():
    evidence = await ProtectSupportBundleAdapter(_manager()).collect("summary", None)

    assert evidence.connection.capabilities.model_dump(mode="json") == {
        "product": "protect",
        "session_available": True,
        "bootstrap_available": True,
        "public_api_key_configured": True,
        "websocket_state": "connected",
    }
    assert evidence.controller.api_surface == "mixed"


async def test_protect_summary_remains_available_after_initialization_returns_false():
    evidence = await ProtectSupportBundleAdapter(_manager(connected=False)).collect("summary", None)

    assert evidence.connection.initialized is False
    assert evidence.probe.status.value == "unavailable"


async def test_protect_resource_shape_is_explicitly_unsupported_after_gate_zero():
    evidence = await ProtectSupportBundleAdapter(_manager()).collect("resource_shape", "sensors")

    assert evidence.probe.model_dump(mode="json") == {
        "probe": "resource_shape",
        "status": "unsupported",
        "resource": "sensors",
        "shape": None,
    }


async def test_protect_connectivity_uses_manager_one_shot_result():
    manager = _manager()
    evidence = await ProtectSupportBundleAdapter(manager).collect("connectivity", None)

    assert evidence.probe.outcome == "timeout"
    assert evidence.probe.duration_bucket == "over_5s"
    manager.support_connectivity_probe.assert_awaited_once_with()
