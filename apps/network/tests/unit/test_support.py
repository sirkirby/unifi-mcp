"""Tests for the Network support-bundle adapter."""

from types import SimpleNamespace

from unifi_core.support_bundle import connection_attempt_failed, connection_attempt_succeeded
from unifi_network_mcp.support import NetworkSupportBundleAdapter


async def test_network_summary_uses_only_public_safe_connection_status():
    manager = SimpleNamespace(
        support_status=lambda: {
            "initialized": True,
            "connected": True,
            "tls_verification_enabled": True,
            "last_attempt": connection_attempt_succeeded(),
            "session_available": True,
            "controller_type": "proxy",
            "reconnect_circuit": "closed",
            "host": "controller.example.invalid",
        }
    )
    adapter = NetworkSupportBundleAdapter(manager, integration_api_key_configured=True)

    evidence = await adapter.collect("summary", None)

    assert evidence.connection.capabilities.model_dump(mode="json") == {
        "product": "network",
        "session_available": True,
        "integration_api_key_configured": True,
        "controller_type": "proxy",
        "reconnect_circuit": "closed",
    }
    assert evidence.controller.api_surface == "mixed"
    assert "controller.example.invalid" not in repr(evidence)


async def test_network_failed_initialization_keeps_category_not_raw_error():
    canary = "https://user:secret@controller.example.invalid"
    manager = SimpleNamespace(
        support_status=lambda: {
            "initialized": False,
            "connected": False,
            "tls_verification_enabled": False,
            "last_attempt": connection_attempt_failed(PermissionError(canary)),
            "session_available": False,
            "controller_type": "unknown",
            "reconnect_circuit": "open",
        }
    )
    adapter = NetworkSupportBundleAdapter(manager, integration_api_key_configured=False)

    evidence = await adapter.collect("summary", None)

    assert evidence.probe.status.value == "unavailable"
    assert evidence.connection.last_attempt.error_category.value == "permission"
    assert canary not in repr(evidence)
