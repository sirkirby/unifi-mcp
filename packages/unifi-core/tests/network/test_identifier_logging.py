"""Identifier-bearing controller operations must keep private data out of logs."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.network.managers.client_manager import ClientManager
from unifi_core.network.managers.device_manager import DeviceManager
from unifi_core.network.managers.network_manager import NetworkManager
from unifi_core.network.managers.traffic_route_manager import TrafficRouteManager


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
    private = f"{mac} {name} controller-error-payload"
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
    for value in (mac, name, "controller-error-payload"):
        assert value not in caplog.text
        assert all(value not in repr(record.args) for record in caplog.records)
    assert all(record.exc_info is None for record in caplog.records)
    if fails:
        assert "RuntimeError" in caplog.text
    # Privacy applies only to logging; the controller must still receive real values.
    assert connection.request.call_args.args[0].data == {"name": name}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["list", "update"])
async def test_traffic_route_failures_log_no_identifiers_or_exception_text(caplog, operation):
    route_id = "private-route-id"
    name = "private-route-name"
    private = f"{route_id} {name} route-client-placeholder controller-error-payload"
    connection = MagicMock()
    connection.site = "default"
    connection.get_cached.return_value = None
    connection.request = AsyncMock(side_effect=RuntimeError(private))
    manager = TrafficRouteManager(connection)

    if operation == "update":
        manager.get_traffic_route_details = AsyncMock(return_value={"_id": route_id, "description": name})
        invoke = manager.update_traffic_route(route_id, enabled=False)
    else:
        invoke = manager.get_traffic_routes()

    with caplog.at_level(logging.DEBUG, logger="unifi-network-mcp"):
        with pytest.raises(RuntimeError):
            await invoke

    assert caplog.records
    for value in (route_id, name, "route-client-placeholder", "controller-error-payload"):
        assert value not in caplog.text
        assert all(value not in repr(record.args) for record in caplog.records)
    assert all(record.exc_info is None for record in caplog.records)
    assert "RuntimeError" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response,private_value",
    [
        ({"data": "network-response-secret-placeholder"}, "network-response-secret-placeholder"),
        ({"data": ["network-entry-secret-placeholder"]}, "network-entry-secret-placeholder"),
    ],
)
async def test_network_list_parse_failures_log_no_controller_response_or_traceback(caplog, response, private_value):
    """Fresh WAN validation must not expose malformed controller responses."""
    connection = MagicMock()
    connection.site = "default"
    connection.get_cached.return_value = None
    connection.request = AsyncMock(return_value=response)

    with caplog.at_level(logging.DEBUG, logger="unifi-network-mcp"):
        with pytest.raises(RuntimeError):
            await NetworkManager(connection).get_networks(force_refresh=True)

    assert caplog.records
    assert private_value not in caplog.text
    assert all(private_value not in repr(record.args) for record in caplog.records)
    assert all(record.exc_info is None for record in caplog.records)
    assert "RuntimeError" in caplog.text
