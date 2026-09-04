"""Identifier-bearing controller operations must keep private data out of logs."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.network.managers.client_manager import ClientManager
from unifi_core.network.managers.device_manager import DeviceManager


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "manager_type,method,lookup",
    [
        (ClientManager, "rename_client", "get_client_details"),
        (DeviceManager, "rename_device", "get_device_details"),
    ],
)
@pytest.mark.parametrize("fails", [False, True])
async def test_rename_logs_exclude_identifiers_and_exception_text(caplog, manager_type, method, lookup, fails):
    mac = "aa:bb:cc:11:22:33"
    name = "private-owner-device"
    private = f"{mac} {name} 192.0.2.41 password=private-password"
    connection = MagicMock()
    connection.request = AsyncMock(side_effect=RuntimeError(private) if fails else None)
    manager = manager_type(connection)
    setattr(manager, lookup, AsyncMock(return_value=SimpleNamespace(raw={"_id": "device-id"})))
    with caplog.at_level(logging.DEBUG, logger="unifi-network-mcp"):
        if fails:
            with pytest.raises(RuntimeError):
                await getattr(manager, method)(mac, name)
        else:
            assert await getattr(manager, method)(mac, name) is True
    assert caplog.records
    for value in (mac, name, "192.0.2.41", "private-password"):
        assert value not in caplog.text
        assert all(value not in repr(record.args) for record in caplog.records)
    assert all(record.exc_info is None for record in caplog.records)
    if fails:
        assert "RuntimeError" in caplog.text
    # Privacy applies only to logging; the controller must still receive real values.
    assert connection.request.call_args.args[0].data == {"name": name}
