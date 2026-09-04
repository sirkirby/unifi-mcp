"""Safe support-status contracts for each product connection manager."""

from __future__ import annotations

import pytest
from unifi_core.access.managers.connection_manager import AccessConnectionManager
from unifi_core.exceptions import UniFiAuthError
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.protect.managers.connection_manager import ProtectConnectionManager


def test_network_support_status_never_exposes_connection_error_text() -> None:
    manager = ConnectionManager("controller.example.invalid", "private-user", "private-password")
    manager._record_connection_error(ConnectionError("private-user private-password https://private.invalid"))
    status = manager.support_status()
    assert status["last_attempt"]["error_category"] == "connection"
    serialized = repr(status)
    assert "private-user" not in serialized
    assert "private-password" not in serialized
    assert "private.invalid" not in serialized


def test_protect_support_status_is_local_and_safe() -> None:
    manager = ProtectConnectionManager(
        "controller.example.invalid",
        "private-user",
        "private-password",
        verify_ssl=True,
        api_key="private-api-key",
    )
    status = manager.support_status()
    assert status == {
        "initialized": False,
        "connected": False,
        "tls_verification_enabled": True,
        "last_attempt": {
            "status": "not_attempted",
            "error_category": None,
            "http_status": None,
            "remediation": None,
        },
        "session_available": False,
        "bootstrap_available": False,
        "public_api_key_configured": True,
        "websocket_state": "unknown",
    }


def test_access_support_status_tracks_unconfigured_paths_without_credentials() -> None:
    manager = AccessConnectionManager("controller.example.invalid", "", "", api_key=None)
    status = manager.support_status()
    assert status["initialized"] is False
    assert status["connected"] is False
    assert status["api_token_configured"] is False
    assert status["developer_api_attempt"]["status"] == "not_configured"
    assert status["proxy_session_attempt"]["status"] == "not_configured"
    assert "controller.example.invalid" not in repr(status)


@pytest.mark.asyncio
async def test_protect_initialize_captures_failure_category_at_failure_time(monkeypatch: pytest.MonkeyPatch) -> None:
    from unifi_core.protect.managers import connection_manager as connection_module

    class PermissionFailure(Exception):
        status = 403

    class FailingClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def update(self) -> None:
            raise PermissionFailure("private host and credential text")

    async def run_once(operation, *, policy):
        del policy
        await operation()

    monkeypatch.setattr(connection_module, "ProtectApiClient", FailingClient)
    monkeypatch.setattr(connection_module, "retry_with_backoff", run_once)
    manager = ProtectConnectionManager("controller.example.invalid", "private-user", "private-password")

    assert await manager.initialize() is False
    status = manager.support_status()
    assert status["last_attempt"]["error_category"] == "permission"
    assert status["last_attempt"]["http_status"] == 403
    assert "private host" not in repr(status)


@pytest.mark.asyncio
async def test_access_proxy_path_captures_failure_without_message(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = AccessConnectionManager("controller.example.invalid", "private-user", "private-password")

    async def fail_login() -> None:
        raise UniFiAuthError("private-user private-password https://private.invalid")

    monkeypatch.setattr(manager, "_proxy_login", fail_login)
    await manager._try_proxy_session()

    status = manager.support_status()
    assert status["proxy_session_attempt"]["error_category"] == "authentication"
    assert "private-user" not in repr(status)
    assert "private-password" not in repr(status)
