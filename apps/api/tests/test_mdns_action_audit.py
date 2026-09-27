"""mDNS action audit privacy through the real settings transport boundary."""

import logging
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiounifi.errors import AiounifiException, RequestError
from unifi_api.services.manifest import ManifestRegistry, ToolEntry
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.managers.system_manager import SystemManager

from tests.test_action_credential_audit import _audit_rows, _post
from tests.test_action_endpoint import _bootstrap

SECRET = "synthetic-controller-only-secret-mdns"
RECORD = {
    "_id": "mdns-id",
    "key": "mdns",
    "mode": "all",
    "predefined_services": [],
    "custom_services": [],
    "enabled_for": "some",
    "enabled_for_network_ids": ["n1", "n2", "n3"],
}


def _real_manager(write_error):
    connection = ConnectionManager("127.0.0.1", "synthetic-user", "synthetic-password")
    session = SimpleNamespace(closed=False)
    controller = MagicMock()
    controller.connectivity.config.session = session
    controller.request = AsyncMock(side_effect=[{"data": [deepcopy(RECORD)]}, write_error])
    connection.controller = controller
    connection._aiohttp_session = session
    connection._initialized = True
    connection.ensure_session_connected = AsyncMock(return_value=True)
    return SystemManager(connection), controller


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("write_error", "expected_error", "expected_applied"),
    [
        (
            AiounifiException({"meta": {"rc": "error", "msg": "api.err.InvalidPayload", "opaque": SECRET}, "data": []}),
            "Controller rejected mDNS settings update (api.err.InvalidPayload)",
            False,
        ),
        (RequestError(f"timeout with {SECRET}"), "mDNS write outcome uncertain", None),
    ],
)
async def test_http_action_audit_contains_only_safe_outcome(
    tmp_path, monkeypatch, caplog, write_error, expected_error, expected_applied
):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "synthetic-db-key")
    app, key, cid = await _bootstrap(tmp_path)
    app.state.manifest_registry = ManifestRegistry(
        {
            "unifi_update_mdns_settings": ToolEntry(
                name="unifi_update_mdns_settings",
                product="network",
                category="system",
                manager="system_manager",
                method="update_mdns_settings",
                permission_action="update",
                read_only_hint=False,
                input_schema={
                    "type": "object",
                    "properties": {"update_data": {"type": "object"}},
                    "required": ["update_data"],
                    "additionalProperties": False,
                },
            )
        }
    )
    manager, controller = _real_manager(write_error)
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)
    app.state.manager_factory = factory

    with caplog.at_level(logging.DEBUG):
        response = await _post(app, key, cid, "unifi_update_mdns_settings", {"update_data": {"mode": "auto"}}, True)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["mutation_applied"] is expected_applied
    assert body["error"].startswith(expected_error)
    assert controller.request.await_count == 2
    rows = await _audit_rows(app, "unifi_update_mdns_settings")
    assert len(rows) == 1 and rows[0].outcome == "error"
    assert SECRET not in response.text + caplog.text + (rows[0].detail or "")
    await app.state.engine.dispose()
