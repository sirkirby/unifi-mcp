"""Verified alternate-address writes, with synthetic controller data only."""

import logging
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiounifi.errors import AiounifiException, Forbidden, NoPermission, RequestError, ResponseError
from unifi_core.network.managers.vpn_manager import VpnManager
from unifi_core.network.models.vpn import (
    ALTERNATE_ADDRESS_KEYS,
    VpnAlternateAddressError,
    VpnAlternateAddressUpdate,
    alternate_address_to_controller_update,
    validate_alternate_address_update,
    vpn_server_from_controller,
)

ENABLED = "vpn_client_configuration_remote_ip_override_enabled"
ADDRESS = "vpn_client_configuration_remote_ip_override"
SECRET = "synthetic-vpn-secret-not-for-output"
BASE = {
    "_id": "srv",
    "purpose": "vpn-server",
    "vpn_type": "wireguard-server",
    ENABLED: False,
    ADDRESS: "old.example.com",
    "nested": {"opaque": [SECRET]},
    "x_wireguard_private_key": SECRET,
    "enabled": True,
}


def manager_with(*responses):
    conn = MagicMock()
    conn.site = "default"
    conn.ensure_session_connected = AsyncMock(return_value=True)
    conn.request = AsyncMock(side_effect=responses)
    return VpnManager(conn), conn


@pytest.mark.parametrize("address", ["vpn.example.com", "gateway", "203.0.113.8", "vpn-1.example", "VPN.Example"])
def test_exact_key_mapping(address):
    assert alternate_address_to_controller_update(
        {"alternate_address_enabled": False, "alternate_address": address}
    ) == {ENABLED: False, ADDRESS: address}


@pytest.mark.parametrize(
    "fields",
    [
        {"unknown": SECRET},
        {"id": "srv"},
        {ENABLED: True},
        {"alternate_address_enabled": None},
        {"alternate_address": None},
        {"alternate_address_enabled": "false"},
        {"alternate_address_enabled": 1},
        {"alternate_address": 123},
        {"alternate_address": True},
        *(
            {"alternate_address": value}
            for value in [
                "",
                " https://vpn.example",
                "https://vpn.example",
                "vpn.example:443",
                "vpn.example/path",
                "::1",
                "[2001:db8::1]",
                "999.2.3.4",
                "a..b",
                "-vpn.example",
                "vpn_.example",
                "a" * 64 + ".example",
            ]
        ),
    ],
)
def test_invalid_inputs_are_value_free(fields):
    with pytest.raises(ValueError) as error:
        validate_alternate_address_update(fields)
    assert SECRET not in str(error.value)
    with pytest.raises(ValueError):
        VpnAlternateAddressUpdate.model_validate(fields)


def test_missing_read_fields_unknown_and_read_write_symmetry():
    view = vpn_server_from_controller({}).model_dump()
    assert view["alternate_address_enabled"] is None
    assert view["alternate_address"] is None
    view = vpn_server_from_controller(BASE).model_dump()
    assert alternate_address_to_controller_update({key: view[key] for key in ALTERNATE_ADDRESS_KEYS}) == {
        ENABLED: False,
        ADDRESS: "old.example.com",
    }


async def test_fresh_full_merge_preserves_secrets_and_never_logs_them(caplog):
    before = deepcopy(BASE)
    after = {**before, ENABLED: True, ADDRESS: "vpn.example.com"}
    manager, conn = manager_with(before_list := [before], {}, [after])
    conn.get_cached.return_value = [{**BASE, "nested": {"stale": True}}]
    with caplog.at_level(logging.DEBUG):
        result = await manager.update_vpn_server_alternate_address(
            "srv", {"alternate_address_enabled": True, "alternate_address": "vpn.example.com"}
        )
    assert result.success and result.mutation_applied is True
    assert set(result.persisted_fields) == set(ALTERNATE_ADDRESS_KEYS)
    calls = conn.request.call_args_list
    assert [call.args[0].method for call in calls] == ["get", "put", "get"]
    put = calls[1].args[0]
    assert put.path == "/rest/networkconf/srv" and put.data == after
    assert put.data["nested"] is not before_list[0]["nested"]
    assert before == BASE
    assert SECRET not in repr(result.to_dict()) + caplog.text
    conn.get_cached.assert_not_called()
    assert conn._invalidate_cache.call_count == 4


async def test_preview_reads_but_never_writes_and_disabling_retains_address():
    manager, conn = manager_with([{**BASE, ENABLED: True}])
    before, after = await manager.prepare_vpn_server_alternate_address("srv", {"alternate_address_enabled": False})
    assert before == {"alternate_address_enabled": True, "alternate_address": "old.example.com"}
    assert after == {"alternate_address_enabled": False, "alternate_address": "old.example.com"}
    assert conn.request.await_count == 1
    assert conn.request.call_args.args[0].method == "get"


async def test_noop_does_not_put():
    manager, conn = manager_with([BASE])
    result = await manager.update_vpn_server_alternate_address("srv", {"alternate_address_enabled": False})
    assert result.success and result.mutation_applied is False
    assert conn.request.await_count == 1


@pytest.mark.parametrize("address", [None, "", "https://bad.example"])
async def test_enabled_requires_effective_address(address):
    manager, conn = manager_with([{**BASE, ADDRESS: address}])
    result = await manager.update_vpn_server_alternate_address("srv", {"alternate_address_enabled": True})
    assert not result.success and result.mutation_applied is False
    assert result.error == (
        "Enabling the alternate address requires a valid alternate_address (supplied or already stored)."
    )
    assert conn.request.await_count == 1


async def test_partial_enable_uses_stored_address():
    manager, conn = manager_with([BASE], {}, [{**BASE, ENABLED: True}])
    result = await manager.update_vpn_server_alternate_address("srv", {"alternate_address_enabled": True})
    assert result.success
    assert conn.request.call_args_list[1].args[0].data[ADDRESS] == BASE[ADDRESS]


async def test_disabling_detects_controller_dropping_saved_address():
    before = {**BASE, ENABLED: True}
    after = {key: value for key, value in BASE.items() if key != ADDRESS}
    manager, conn = manager_with([before], {}, [after])
    result = await manager.update_vpn_server_alternate_address("srv", {"alternate_address_enabled": False})
    assert not result.success and result.partial_success
    assert result.dropped_fields == ("alternate_address",)
    assert result.persisted_fields == ("alternate_address_enabled",)
    assert conn.request.call_args_list[1].args[0].data[ADDRESS] == BASE[ADDRESS]


async def test_partial_persistence_is_not_success():
    manager, _ = manager_with([BASE], {}, [{**BASE, ENABLED: True}])
    result = await manager.update_vpn_server_alternate_address(
        "srv", {"alternate_address_enabled": True, "alternate_address": "new.example"}
    )
    assert not result.success and result.partial_success and result.mutation_applied is True
    assert result.dropped_fields == ("alternate_address",)


@pytest.mark.parametrize(
    "record",
    [
        {"_id": "srv", "purpose": "corporate"},
        {**BASE, "purpose": "vpn-client"},
        {**BASE, "vpn_type": "wireguard-client"},
        {**BASE, "vpn_type": "openvpn-server"},
        {**BASE, "vpn_type": "guessed-server"},
    ],
)
async def test_rejects_client_nonvpn_and_unverified_server_types(record):
    manager, conn = manager_with([record])
    result = await manager.update_vpn_server_alternate_address("srv", {"alternate_address_enabled": True})
    assert not result.success and result.mutation_applied is False
    assert result.error == "VPN alternate-address updates require a WireGuard VPN server"
    assert conn.request.await_count == 1


@pytest.mark.parametrize(
    "record, dropped, coerced",
    [
        (BASE, ("alternate_address_enabled",), ()),
        ({key: value for key, value in BASE.items() if key != ENABLED}, ("alternate_address_enabled",), ()),
        ({**BASE, ENABLED: 1}, (), ("alternate_address_enabled",)),
    ],
)
async def test_dropped_missing_and_coerced_values(record, dropped, coerced):
    manager, _ = manager_with([BASE], {}, [record])
    result = await manager.update_vpn_server_alternate_address("srv", {"alternate_address_enabled": True})
    assert not result.success
    assert result.dropped_fields == dropped and result.coerced_fields == coerced
    assert SECRET not in repr(result.to_dict())


@pytest.mark.parametrize("readback", [RequestError(SECRET), [], {"bad": SECRET}])
async def test_readback_failures_are_uncertain(readback, caplog):
    manager, conn = manager_with([BASE], {}, readback)
    result = await manager.update_vpn_server_alternate_address("srv", {"alternate_address_enabled": True})
    assert not result.success and result.mutation_applied is None
    assert SECRET not in repr(result.to_dict()) + caplog.text
    assert conn.request.await_count == 3


@pytest.mark.parametrize(
    "error, applied",
    [
        (RequestError(SECRET), None),
        (TimeoutError(SECRET), None),
        (Forbidden(SECRET), False),
        (NoPermission(SECRET), False),
        (ResponseError(f"Call https://controller.invalid/rest/networkconf/srv received 400: {SECRET}"), False),
        (AiounifiException({"meta": {"rc": "error", "msg": "api.err.InvalidPayload", "opaque": SECRET}}), False),
    ],
)
async def test_write_failures_not_retried_and_classified_safely(error, applied, caplog):
    manager, conn = manager_with([BASE], error)
    result = await manager.update_vpn_server_alternate_address("srv", {"alternate_address_enabled": True})
    assert not result.success and result.mutation_applied is applied
    assert conn.request.await_count == 2
    assert conn._invalidate_cache.call_count == 4
    assert SECRET not in repr(result.to_dict()) + caplog.text


async def test_session_required_before_read_or_write():
    manager, conn = manager_with()
    conn.ensure_session_connected.return_value = False
    result = await manager.update_vpn_server_alternate_address("srv", {"alternate_address_enabled": False})
    assert not result.success and result.mutation_applied is False
    assert result.error == "VPN alternate-address update requires Network session authentication"
    conn.request.assert_not_awaited()


async def test_invalid_direct_manager_input_rejected_before_io():
    manager, conn = manager_with()
    result = await manager.update_vpn_server_alternate_address("srv", {"name": SECRET})
    assert not result.success and result.mutation_applied is False
    assert SECRET not in result.error
    conn.request.assert_not_awaited()


async def test_empty_update_rejected_before_io_by_model_preview_and_apply():
    with pytest.raises(ValueError, match="Supply at least one"):
        VpnAlternateAddressUpdate.model_validate({})
    manager, conn = manager_with()
    with pytest.raises(VpnAlternateAddressError, match="Supply at least one"):
        await manager.prepare_vpn_server_alternate_address("srv", {})
    result = await manager.update_vpn_server_alternate_address("srv", {})
    assert not result.success and result.mutation_applied is False
    assert result.error.startswith("Supply at least one")
    conn.ensure_session_connected.assert_not_awaited()
    conn.request.assert_not_awaited()


@pytest.mark.parametrize("error_type", [ValueError, RuntimeError])
@pytest.mark.parametrize("boundary", ["session", "read", "unexpected"])
async def test_preflight_unexpected_errors_never_echo_controller_text(error_type, boundary, caplog):
    manager, conn = manager_with()
    if boundary == "session":
        conn.ensure_session_connected.side_effect = error_type(SECRET)
    elif boundary == "read":
        conn.request.side_effect = error_type(SECRET)
    else:
        manager._prepare_alternate_address_update = AsyncMock(side_effect=error_type(SECRET))
    result = await manager.update_vpn_server_alternate_address("srv", {"alternate_address_enabled": True})
    assert not result.success and result.mutation_applied is False
    assert SECRET not in repr(result.to_dict()) + caplog.text
    assert all(call.args[0].method == "get" for call in conn.request.call_args_list)
