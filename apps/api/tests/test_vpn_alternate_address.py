"""VPN alternate-address direct dispatch and durable audit privacy."""

import logging
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiounifi.errors import AiounifiException, RequestError
from unifi_api.graphql.types.network.vpn import VpnServer
from unifi_api.services.actions import MutationPreview, dispatch_action
from unifi_api.services.manifest import ManifestRegistry, ToolEntry
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.managers.vpn_manager import VpnManager
from unifi_core.network.models.vpn import VpnAlternateAddressToolInput, vpn_alternate_address_input_schema

from tests.test_action_credential_audit import _audit_rows, _post
from tests.test_action_endpoint import _bootstrap

TOOL = "unifi_update_vpn_server_alternate_address"
ENABLED = "vpn_client_configuration_remote_ip_override_enabled"
ADDRESS = "vpn_client_configuration_remote_ip_override"
SECRET = "synthetic-controller-only-vpn-secret"
RECORD = {"_id": "srv", "vpn_type": "wireguard-server", ENABLED: False, ADDRESS: "vpn.example", "opaque": SECRET}


def registry():
    schema = vpn_alternate_address_input_schema(VpnAlternateAddressToolInput)
    schema["properties"].pop("confirm")
    return ManifestRegistry(
        {
            TOOL: ToolEntry(
                name=TOOL,
                product="network",
                category="vpn_servers",
                manager="vpn_manager",
                method="update_vpn_server_alternate_address",
                permission_action="update",
                read_only_hint=False,
                auth_method="local_only",
                input_schema=schema,
            )
        }
    )


def real_manager(*responses):
    conn = ConnectionManager("127.0.0.1", "synthetic-user", "synthetic-password")
    session = SimpleNamespace(closed=False)
    controller = MagicMock()
    controller.connectivity.config.session = session
    controller.request = AsyncMock(side_effect=responses)
    conn.controller = controller
    conn._aiohttp_session = session
    conn._initialized = True
    conn.ensure_session_connected = AsyncMock(return_value=True)
    return VpnManager(conn), controller


async def dispatch(factory, fields, confirm=True):
    return await dispatch_action(
        registry=registry(),
        factory=factory,
        session=MagicMock(),
        tool_name=TOOL,
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args={"server_id": "srv", "update_data": fields},
        confirm=confirm,
    )


@pytest.mark.asyncio
async def test_direct_dispatch_uses_real_manager_validation_and_verification():
    manager, controller = real_manager(
        {"data": [deepcopy(RECORD)]}, {"data": []}, {"data": [{**RECORD, ENABLED: True}]}
    )
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)
    result = await dispatch(factory, {"alternate_address_enabled": True})
    assert result.success and result.persisted_fields == ("alternate_address_enabled",)
    assert controller.request.call_args_list[1].args[0].data["opaque"] == SECRET
    assert SECRET not in repr(result.to_dict())


@pytest.mark.asyncio
async def test_api_preview_is_arguments_only_without_manager_io():
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock()
    result = await dispatch(factory, {"alternate_address_enabled": True}, confirm=False)
    assert isinstance(result, MutationPreview)
    factory.get_domain_manager.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fields", [{}, {"alternate_address_enabled": "false"}, {"alternate_address": None}, {"name": SECRET}]
)
@pytest.mark.parametrize("confirm", [False, True])
async def test_api_rejects_invalid_partial_inputs_before_manager(fields, confirm):
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock()
    with pytest.raises(ValueError) as exc:
        await dispatch(factory, fields, confirm=confirm)
    assert SECRET not in str(exc.value)
    factory.get_domain_manager.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_dispatch_checks_effective_state():
    manager, controller = real_manager({"data": [{key: value for key, value in RECORD.items() if key != ADDRESS}]})
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)
    result = await dispatch(factory, {"alternate_address_enabled": True})
    assert not result.success and result.mutation_applied is False
    assert result.error == (
        "Enabling the alternate address requires a valid alternate_address (supplied or already stored)."
    )
    assert controller.request.await_count == 1


@pytest.mark.parametrize("raw, enabled, address", [({}, None, None), (RECORD, False, "vpn.example")])
def test_api_read_projection_unknown_and_false(raw, enabled, address):
    output = VpnServer.from_manager_output(raw).to_dict()
    assert output["alternate_address_enabled"] is enabled
    assert output["alternate_address"] == address
    assert SECRET not in repr(output)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error, applied",
    [
        (
            AiounifiException({"meta": {"rc": "error", "msg": "api.err.InvalidPayload", "opaque": SECRET}, "data": []}),
            False,
        ),
        (RequestError(SECRET), None),
    ],
)
async def test_http_audit_contains_only_safe_outcome(tmp_path, monkeypatch, caplog, error, applied):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "synthetic-db-key")
    monkeypatch.setenv("UNIFI_MCP_DIAGNOSTICS", "true")
    app, key, cid = await _bootstrap(tmp_path)
    app.state.manifest_registry = registry()
    manager, controller = real_manager({"data": [deepcopy(RECORD)]}, error)
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)
    app.state.manager_factory = factory
    with caplog.at_level(logging.DEBUG):
        response = await _post(
            app, key, cid, TOOL, {"server_id": "srv", "update_data": {"alternate_address_enabled": True}}, True
        )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False and body["mutation_applied"] is applied
    assert controller.request.await_count == 2
    rows = await _audit_rows(app, TOOL)
    assert len(rows) == 1 and rows[0].outcome == "error"
    assert SECRET not in response.text + caplog.text + (rows[0].detail or "")
    await app.state.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case, expected",
    [
        ("target", "VPN alternate-address updates require a WireGuard VPN server"),
        ("missing", "VPN alternate-address target was not found or is ambiguous"),
        ("session", "VPN alternate-address update requires Network session authentication"),
        ("address", "Enabling the alternate address requires a valid alternate_address (supplied or already stored)."),
        ("read_value", "Failed to read VPN alternate-address configuration"),
        ("read_runtime", "Failed to read VPN alternate-address configuration"),
    ],
)
async def test_http_preflight_reports_not_applied_and_safe_reason(tmp_path, monkeypatch, caplog, case, expected):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "synthetic-db-key")
    app, key, cid = await _bootstrap(tmp_path)
    app.state.manifest_registry = registry()
    record = deepcopy(RECORD)
    if case == "target":
        record["vpn_type"] = "wireguard-client"
    if case == "address":
        record.pop(ADDRESS)
    reply = {"data": [] if case == "missing" else [record]}
    if case == "read_value":
        reply = ValueError(SECRET)
    elif case == "read_runtime":
        reply = RuntimeError(SECRET)
    manager, controller = real_manager(reply)
    if case == "session":
        manager._connection.ensure_session_connected.return_value = False
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)
    app.state.manager_factory = factory
    with caplog.at_level(logging.DEBUG):
        response = await _post(
            app, key, cid, TOOL, {"server_id": "srv", "update_data": {"alternate_address_enabled": True}}, True
        )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False and body["mutation_applied"] is False
    assert body["error"] == expected
    assert all(call.args[0].method == "get" for call in controller.request.call_args_list)
    rows = await _audit_rows(app, TOOL)
    assert len(rows) == 1 and rows[0].outcome == "error"
    assert SECRET not in response.text + caplog.text + (rows[0].detail or "")
    await app.state.engine.dispose()
