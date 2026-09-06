"""SNMP tool responses and logs must not carry submitted credential values.

Drives the real ``SystemManager`` and ``ConnectionManager`` with a fake
aiounifi controller whose request fails with an error quoting the submitted
secret. Asserts the MCP tool response and
the captured log are both free of the sentinel, for preview and write.
"""

import logging
import os

import pytest
from aiounifi.errors import ResponseError

from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.managers.system_manager import SystemManager

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")

SENTINEL = "SENTINEL-community-secret-4b1d"
LOGIN_SENTINEL = "SENTINEL-login-secret-0e77"


class _Session:
    closed = False

    async def close(self):
        return None


class _Config:
    def __init__(self):
        self.session = _Session()


class _Connectivity:
    def __init__(self):
        self.can_retry_login = True
        self.config = _Config()
        self.is_unifi_os = True


class _Controller:
    def __init__(self, raiser):
        self.connectivity = _Connectivity()
        self._raiser = raiser

    async def login(self):
        self.connectivity.can_retry_login = False

    async def request(self, api_request):
        return self._raiser(api_request)


def _auth_failure(_api_request):
    raise ResponseError(f"auth failed for admin:{LOGIN_SENTINEL}")


def _system_manager(raiser):
    controller = _Controller(raiser)
    connection = ConnectionManager("192.168.1.1", "admin", LOGIN_SENTINEL)
    connection.controller = controller
    connection._aiohttp_session = controller.connectivity.config.session
    connection._initialized = True
    connection._auth_generation = 1
    return SystemManager(connection)


@pytest.mark.asyncio
async def test_update_snmp_write_error_response_and_log_are_scrubbed(monkeypatch, caplog):
    from unifi_network_mcp.tools import system

    def _raiser(api_request):
        if api_request.method == "get":
            return {"data": [{"_id": "snmp-1", "key": "snmp", "enabled": False}]}
        raise ResponseError(f"controller rejected {api_request.data!r}")

    manager = _system_manager(_raiser)
    monkeypatch.setattr(system, "system_manager", manager)
    caplog.set_level(logging.DEBUG)

    result = await system.update_snmp_settings(enabled=True, community=SENTINEL, confirm=True)

    assert result["success"] is False
    assert SENTINEL not in repr(result)
    assert SENTINEL not in caplog.text
    await manager._connection.cleanup()


@pytest.mark.asyncio
async def test_update_snmp_preview_read_error_response_and_log_are_scrubbed(monkeypatch, caplog):
    """Preview only reads; the transport error can still quote the login credential."""
    from unifi_network_mcp.tools import system

    manager = _system_manager(_auth_failure)
    monkeypatch.setattr(system, "system_manager", manager)
    caplog.set_level(logging.DEBUG)

    result = await system.update_snmp_settings(enabled=True, community=SENTINEL, confirm=False)

    assert result["success"] is False
    assert LOGIN_SENTINEL not in repr(result)
    assert LOGIN_SENTINEL not in caplog.text
    await manager._connection.cleanup()


@pytest.mark.asyncio
async def test_get_snmp_read_error_response_and_log_are_scrubbed(monkeypatch, caplog):
    from unifi_network_mcp.tools import system

    manager = _system_manager(_auth_failure)
    monkeypatch.setattr(system, "system_manager", manager)
    caplog.set_level(logging.DEBUG)

    result = await system.get_snmp_settings()

    assert result["success"] is False
    assert LOGIN_SENTINEL not in repr(result)
    assert LOGIN_SENTINEL not in caplog.text
    await manager._connection.cleanup()
