"""Core CyberSecure read and allowlisted projection tests (no controller I/O)."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.network.managers.system_manager import SystemManager
from unifi_core.network.models.threat_posture import (
    GATEWAY_SIGNATURE_READ_ONLY_FIELDS,
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    GatewaySignature,
    ThreatPosture,
    threat_posture_from_controller,
)


def _device(**overrides):
    raw = {
        "_id": "device-1",
        "mac": "aa:bb:cc:dd:ee:ff",
        "name": "Gateway",
        "ids_ips_signature": {
            "rule_count": 42,
            "update_time": 1786225096952,
            "signature_type": "ids",
            "is_activating": False,
            "sha_256": "secret-hash",
        },
        "controller_token": "secret-token",
    }
    raw.update(overrides)
    return SimpleNamespace(raw=raw)


def test_read_only_field_contract_and_descriptions():
    assert MUTABLE_FIELDS == frozenset()
    assert READ_ONLY_FIELDS == frozenset(ThreatPosture.model_fields)
    assert GATEWAY_SIGNATURE_READ_ONLY_FIELDS == frozenset(GatewaySignature.model_fields)
    for model in (ThreatPosture, GatewaySignature):
        for field in model.model_fields.values():
            assert field.description
            assert field.json_schema_extra == {"mutable": False}
    assert "milliseconds" in ThreatPosture.model_fields["updated_timestamp"].description
    assert "milliseconds" in GatewaySignature.model_fields["update_time"].description
    assert "Integration API" in GatewaySignature.model_fields["device_id"].description


def test_projection_is_strict_and_excludes_unknown_keys(monkeypatch):
    monkeypatch.setenv("UNIFI_REDACT_SENSITIVE_FIELDS", "false")
    summary = {
        "enterprise": True,
        "has_subscription": False,
        "ips_enabled": True,
        "is_activating": False,
        "scanned_bytes": 123,
        "signature_capacity": 456,
        "signatures": 789,
        "threats": 2,
        "updated_timestamp": 1786225096952,
        "controller_token": "secret-token",
    }
    result = threat_posture_from_controller("DAY", summary, [_device()])

    assert isinstance(result, ThreatPosture)
    assert result.period == "DAY"
    assert result.enterprise is True
    assert result.has_subscription is False
    assert result.scanned_bytes == 123
    assert result.updated_timestamp == 1786225096952
    assert len(result.gateway_signatures) == 1
    assert result.gateway_signatures[0].rule_count == 42
    assert result.gateway_signatures[0].update_time == 1786225096952
    dumped = result.model_dump()
    assert set(dumped) == {"period", "gateway_signatures", *summary.keys() - {"controller_token"}}
    assert set(dumped["gateway_signatures"][0]) == {
        "device_id",
        "mac_address",
        "name",
        "rule_count",
        "update_time",
        "signature_type",
        "is_activating",
    }
    assert "secret-hash" not in repr(dumped)
    assert "secret-token" not in repr(dumped)


def test_missing_and_wrong_types_remain_unknown():
    result = threat_posture_from_controller(
        "HOUR",
        {"enterprise": 1, "ips_enabled": "false", "scanned_bytes": True, "threats": "3"},
        [
            _device(
                _id=7,
                name=False,
                ids_ips_signature={"rule_count": True, "update_time": "12", "signature_type": 2, "is_activating": 0},
            )
        ],
    )
    assert result.enterprise is None
    assert result.has_subscription is None
    assert result.ips_enabled is None
    assert result.is_activating is None
    assert result.scanned_bytes is None
    assert result.signature_capacity is None
    assert result.signatures is None
    assert result.threats is None
    assert result.updated_timestamp is None
    gateway = result.gateway_signatures[0]
    assert gateway.device_id is None
    assert gateway.mac_address == "aa:bb:cc:dd:ee:ff"
    assert gateway.name is None
    assert gateway.rule_count is None
    assert gateway.update_time is None
    assert gateway.signature_type is None
    assert gateway.is_activating is None


def test_only_devices_with_verified_signature_object_are_included():
    result = threat_posture_from_controller(
        "DAY", {}, [_device(ids_ips_signature=None), _device(ids_ips_signature=[]), object()]
    )
    assert result.gateway_signatures == []


@pytest.mark.asyncio
async def test_manager_requests_summary_then_device_collection():
    connection = MagicMock()
    connection.ensure_session_connected = AsyncMock(return_value=True)
    connection.request = AsyncMock(return_value=[{"threats": 3}])
    devices = [_device()]
    connection.controller = SimpleNamespace(devices={"gateway": devices[0]})
    connection.refresh_handler = AsyncMock()
    result = await SystemManager(connection).get_threat_posture("WEEK")
    assert result.period == "WEEK"
    assert result.threats == 3
    connection.ensure_session_connected.assert_awaited_once_with()
    request = connection.request.await_args.args[0]
    assert request.method == "get"
    assert request.path == "/cybersecure/summary?period=WEEK"
    connection.refresh_handler.assert_awaited_once_with("devices")
    assert result.gateway_signatures[0].device_id == "device-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("period", ["HOUR", "DAY", "WEEK", "MONTH"])
async def test_all_verified_periods(period):
    connection = MagicMock()
    connection.ensure_session_connected = AsyncMock(return_value=True)
    connection.request = AsyncMock(return_value=[{}])
    connection.controller = SimpleNamespace(devices={})
    connection.refresh_handler = AsyncMock()
    result = await SystemManager(connection).get_threat_posture(period)
    assert result.period == period
    assert connection.request.await_args.args[0].path == f"/cybersecure/summary?period={period}"


@pytest.mark.asyncio
@pytest.mark.parametrize("period", ["day", "YEAR", "DAY&admin=true", None, 1, True])
async def test_invalid_period_rejected_before_io(period):
    connection = MagicMock()
    connection.ensure_session_connected = AsyncMock()
    connection.request = AsyncMock()
    connection.refresh_handler = AsyncMock()
    with pytest.raises(ValueError, match="Invalid threat posture period"):
        await SystemManager(connection).get_threat_posture(period)
    connection.ensure_session_connected.assert_not_awaited()
    connection.request.assert_not_awaited()
    connection.refresh_handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_session_is_required_before_summary_or_device_calls():
    connection = MagicMock()
    connection.ensure_session_connected = AsyncMock(return_value=False)
    connection.request = AsyncMock()
    connection.refresh_handler = AsyncMock()
    with pytest.raises(RuntimeError, match="requires Network session authentication") as error:
        await SystemManager(connection).get_threat_posture()
    assert error.value.__cause__ is None
    connection.request.assert_not_awaited()
    connection.refresh_handler.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [[], {}, [None], [{}, {}], "bad"])
async def test_unexpected_envelope_fails_safely_before_devices(response, caplog):
    connection = MagicMock()
    connection.ensure_session_connected = AsyncMock(return_value=True)
    connection.request = AsyncMock(return_value=response)
    connection.refresh_handler = AsyncMock()
    with caplog.at_level(logging.DEBUG, logger="unifi-network-mcp"):
        with pytest.raises(RuntimeError, match="Unexpected threat posture summary response") as error:
            await SystemManager(connection).get_threat_posture()
    assert error.value.__cause__ is None
    connection.refresh_handler.assert_not_awaited()
    assert "secret" not in caplog.text


@pytest.mark.asyncio
async def test_controller_exception_is_not_exposed_or_chained(caplog):
    connection = MagicMock()
    connection.ensure_session_connected = AsyncMock(return_value=True)
    connection.request = AsyncMock(side_effect=RuntimeError("secret token and device id"))
    with caplog.at_level(logging.DEBUG, logger="unifi-network-mcp"):
        with pytest.raises(RuntimeError, match="Failed to read threat posture") as error:
            await SystemManager(connection).get_threat_posture()
    assert error.value.__cause__ is None
    assert "secret token" not in str(error.value)
    assert "secret token" not in caplog.text


@pytest.mark.asyncio
async def test_device_refresh_exception_is_not_exposed(caplog):
    connection = MagicMock()
    connection.ensure_session_connected = AsyncMock(return_value=True)
    connection.request = AsyncMock(return_value=[{}])
    connection.controller = SimpleNamespace(devices={})
    connection.refresh_handler = AsyncMock(side_effect=RuntimeError("secret device id"))
    with caplog.at_level(logging.DEBUG, logger="unifi-network-mcp"):
        with pytest.raises(RuntimeError, match="Failed to read threat posture") as error:
            await SystemManager(connection).get_threat_posture()
    assert error.value.__cause__ is None
    assert "secret device id" not in str(error.value)
    assert "secret device id" not in caplog.text


@pytest.mark.asyncio
async def test_missing_controller_fails_before_device_refresh():
    connection = MagicMock()
    connection.ensure_session_connected = AsyncMock(return_value=True)
    connection.request = AsyncMock(return_value=[{}])
    connection.controller = None
    connection.refresh_handler = AsyncMock()
    with pytest.raises(RuntimeError, match="Failed to read threat posture"):
        await SystemManager(connection).get_threat_posture()
    connection.refresh_handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_controller_lost_during_device_refresh_fails_safely():
    connection = MagicMock()
    connection.ensure_session_connected = AsyncMock(return_value=True)
    connection.request = AsyncMock(return_value=[{}])
    connection.controller = SimpleNamespace(devices={})

    async def lose_controller(_name):
        connection.controller = None

    connection.refresh_handler = AsyncMock(side_effect=lose_controller)
    with pytest.raises(RuntimeError, match="Failed to read threat posture") as error:
        await SystemManager(connection).get_threat_posture()
    assert error.value.__cause__ is None
    connection.refresh_handler.assert_awaited_once_with("devices")
