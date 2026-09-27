"""Exercise mDNS result classification through the real settings transport boundary."""

import logging
import traceback
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiounifi.errors import AiounifiException, LoginRequired, RequestError
from aiounifi.models.api import ApiRequest
from unifi_core.network.managers.connection_manager import ConnectionManager, SettingsControllerRejection
from unifi_core.network.managers.system_manager import SystemManager

SECRET = "synthetic-controller-only-secret"
RECORD = {
    "_id": "mdns-id",
    "key": "mdns",
    "mode": "all",
    "predefined_services": [],
    "custom_services": [],
    "enabled_for": "some",
    "enabled_for_network_ids": ["n1", "n2", "n3"],
}


def _connection(*responses):
    connection = ConnectionManager("127.0.0.1", "synthetic-user", "synthetic-password")
    session = SimpleNamespace(closed=False)
    controller = MagicMock()
    controller.connectivity.config.session = session
    controller.request = AsyncMock(side_effect=responses)
    connection.controller = controller
    connection._aiohttp_session = session
    connection._initialized = True
    connection.ensure_session_connected = AsyncMock(return_value=True)
    return connection, controller


@pytest.mark.asyncio
async def test_controller_rejection_survives_real_settings_translation_safely(caplog):
    rejection = AiounifiException(
        {"meta": {"rc": "error", "msg": "api.err.InvalidPayload", "opaque": SECRET}, "data": []}
    )
    connection, controller = _connection({"data": [deepcopy(RECORD)]}, rejection)
    with caplog.at_level(logging.DEBUG, logger="unifi-network-mcp"):
        result = await SystemManager(connection).update_mdns_settings({"mode": "auto"})

    assert result.success is False
    assert result.mutation_applied is False
    assert result.error == "Controller rejected mDNS settings update (api.err.InvalidPayload)"
    assert controller.request.await_count == 2
    assert SECRET not in caplog.text + repr(result.to_dict())
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
async def test_timeout_through_real_settings_translation_is_uncertain(caplog):
    connection, controller = _connection({"data": [deepcopy(RECORD)]}, RequestError(f"timeout with {SECRET}"))
    with caplog.at_level(logging.DEBUG, logger="unifi-network-mcp"):
        result = await SystemManager(connection).update_mdns_settings({"mode": "auto"})

    assert result.success is False
    assert result.mutation_applied is None
    assert result.metadata["outcome_uncertain"] is True
    assert controller.request.await_count == 2
    assert SECRET not in caplog.text + repr(result.to_dict())
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
async def test_safe_rejection_has_no_raw_context_or_body():
    rejection = AiounifiException(
        {"meta": {"rc": "error", "msg": "api.err.InvalidPayload", "opaque": SECRET}, "data": []}
    )
    connection, _ = _connection(rejection)
    with pytest.raises(SettingsControllerRejection) as raised:
        await connection.request(ApiRequest(method="put", path="/set/setting/mdns", data={"mode": "auto"}))
    error = raised.value
    assert error.code == "api.err.InvalidPayload"
    assert error.__cause__ is None
    assert error.__context__ is None
    assert error.args == ("Controller settings request rejected.",)
    assert vars(error) == {"code": "api.err.InvalidPayload"}
    assert SECRET not in "".join(traceback.format_exception(error))


@pytest.mark.asyncio
async def test_reauthenticated_retry_rejection_keeps_only_safe_code(caplog):
    rejection = AiounifiException(
        {"meta": {"rc": "error", "msg": "api.err.InvalidPayload", "opaque": SECRET}, "data": []}
    )
    connection, controller = _connection(LoginRequired(f"login required: {SECRET}"), rejection)
    connection._reauthenticate = AsyncMock(return_value=True)
    with caplog.at_level(logging.DEBUG, logger="unifi-network-mcp"):
        with pytest.raises(SettingsControllerRejection) as raised:
            await connection.request(ApiRequest(method="put", path="/set/setting/mdns", data={"mode": "auto"}))

    error = raised.value
    assert controller.request.await_count == 2
    assert controller.request.await_args_list[0].args[0] is controller.request.await_args_list[1].args[0]
    connection._reauthenticate.assert_awaited_once()
    assert error.code == "api.err.InvalidPayload"
    assert error.__cause__ is None and error.__context__ is None
    assert vars(error) == {"code": "api.err.InvalidPayload"}
    assert SECRET not in caplog.text + "".join(traceback.format_exception(error))
