"""Tests for the Access support-bundle adapter."""

from types import SimpleNamespace

from unifi_access_mcp.support import AccessSupportBundleAdapter
from unifi_core.support_bundle import connection_attempt_succeeded


def _manager(*, developer: bool, proxy: bool):
    return SimpleNamespace(
        support_status=lambda: {
            "initialized": developer or proxy,
            "connected": developer or proxy,
            "tls_verification_enabled": True,
            "last_attempt": connection_attempt_succeeded(),
            "developer_api_available": developer,
            "proxy_session_available": proxy,
            "api_token_configured": True,
            "developer_api_attempt": connection_attempt_succeeded(),
            "proxy_session_attempt": connection_attempt_succeeded(),
        }
    )


async def test_access_summary_reports_dual_auth_capabilities_without_attempt_extras():
    evidence = await AccessSupportBundleAdapter(_manager(developer=True, proxy=True)).collect("summary", None)

    assert evidence.connection.capabilities.model_dump(mode="json") == {
        "product": "access",
        "developer_api_available": True,
        "proxy_session_available": True,
        "api_token_configured": True,
    }
    assert evidence.controller.api_surface == "mixed"
    assert "developer_api_attempt" not in repr(evidence)


async def test_access_single_successful_auth_path_is_reported():
    developer = await AccessSupportBundleAdapter(_manager(developer=True, proxy=False)).collect("summary", None)
    proxy = await AccessSupportBundleAdapter(_manager(developer=False, proxy=True)).collect("summary", None)

    assert developer.controller.api_surface == "integration"
    assert proxy.controller.api_surface == "controller_v2"
