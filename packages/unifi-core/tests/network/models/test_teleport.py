"""Teleport field, validation and write-verification contracts."""

from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiounifi.errors import RequestError
from unifi_core.network.managers.connection_manager import SettingsControllerRejection
from unifi_core.network.managers.vpn_manager import VpnManager
from unifi_core.network.models.teleport import (
    TELEPORTSETTINGS_MUTABLE_FIELDS,
    TELEPORTSETTINGS_READ_ONLY_FIELDS,
    teleport_from_controller,
    teleport_subnet_conflicts,
    teleport_to_controller_update,
)

RECORD = {
    "_id": "teleport-id",
    "key": "teleport",
    "site_id": "site-id",
    "enabled": True,
    "subnet_cidr": "192.168.2.1/24",
    "future_setting": {"nested": [1]},
}

NETWORKS = [
    {"_id": "n1", "name": "Default", "purpose": "corporate", "ip_subnet": "10.100.0.1/16"},
    {"_id": "n2", "name": "Guests", "purpose": "guest", "ip_subnet": "10.110.0.1/24"},
    {"_id": "n3", "name": "WireGuard", "purpose": "remote-user-vpn", "ip_subnet": "10.120.0.1/24"},
    {"_id": "n4", "name": "Uplink", "purpose": "wan"},
    {"_id": "n5", "name": "Broken", "purpose": "corporate", "ip_subnet": "not-a-subnet"},
]


def test_field_sets():
    assert TELEPORTSETTINGS_MUTABLE_FIELDS == frozenset({"subnet_cidr"})
    assert TELEPORTSETTINGS_READ_ONLY_FIELDS == frozenset({"enabled", "id", "site_id"})


def test_read_projects_known_fields_only():
    settings = teleport_from_controller([deepcopy(RECORD)]).model_dump()
    assert settings == {
        "enabled": True,
        "subnet_cidr": "192.168.2.1/24",
        "id": "teleport-id",
        "site_id": "site-id",
    }


@pytest.mark.parametrize("raw", [None, [], {}, "bad"])
def test_read_of_missing_record_is_empty(raw):
    assert teleport_from_controller(raw).model_dump() == {
        "enabled": None,
        "subnet_cidr": None,
        "id": None,
        "site_id": None,
    }


def test_read_tolerates_record_without_range():
    # Records of sites where Teleport was never enabled carry no subnet_cidr.
    settings = teleport_from_controller({"_id": "t", "key": "teleport", "enabled": False})
    assert settings.enabled is False
    assert settings.subnet_cidr is None


@pytest.mark.parametrize(
    "value",
    ["10.201.0.1/24", "172.16.5.1/24", "192.168.77.1/24", "10.20.0.1/16", "10.30.9.9/29"],
)
def test_valid_ranges_pass(value):
    assert teleport_to_controller_update({"subnet_cidr": value}) == {"subnet_cidr": value}


def test_surrounding_whitespace_is_trimmed():
    assert teleport_to_controller_update({"subnet_cidr": " 10.201.0.1/24 "}) == {"subnet_cidr": "10.201.0.1/24"}


@pytest.mark.parametrize(
    ("value", "rule"),
    [
        ("", "non-empty"),
        (None, "non-empty"),
        (24, "non-empty"),
        ("10.77.0.1", "prefix length"),
        ("10.201.0.300/24", "IPv4 address"),
        ("fd00::1/64", "IPv4 address"),
        ("10.201.0.1/8", "between /16 and /29"),
        ("10.201.0.1/30", "between /16 and /29"),
        ("8.8.8.1/24", "private"),
        ("100.64.0.1/24", "private"),
        ("10.201.0.0/24", "gateway address"),
        ("10.201.0.255/24", "gateway address"),
    ],
)
def test_invalid_ranges_name_the_rule_not_the_value(value, rule):
    with pytest.raises(ValueError) as raised:
        teleport_to_controller_update({"subnet_cidr": value})
    assert rule in str(raised.value)
    if isinstance(value, str) and value:
        assert value not in str(raised.value)


@pytest.mark.parametrize("fields", [{}, {"enabled": False}, {"subnet_cidr": "10.201.0.1/24", "enabled": True}])
def test_only_subnet_is_writable(fields):
    with pytest.raises(ValueError, match="Teleport field"):
        teleport_to_controller_update(fields)


def test_overlap_check_covers_lans_and_vpn_ranges():
    assert teleport_subnet_conflicts("10.201.0.1/24", NETWORKS) == []
    assert teleport_subnet_conflicts("10.100.5.1/24", NETWORKS) == ["Default"]
    assert teleport_subnet_conflicts("10.120.0.1/24", NETWORKS) == ["WireGuard"]
    assert teleport_subnet_conflicts("10.0.0.1/8", NETWORKS) == ["Default", "Guests", "WireGuard"]


def manager_and_connection(responses):
    conn = MagicMock()
    conn.site = "default"
    conn.request = AsyncMock(side_effect=responses)
    conn.ensure_session_connected = AsyncMock(return_value=True)
    conn._invalidate_cache = MagicMock()
    return VpnManager(conn), conn


@pytest.mark.asyncio
async def test_get_reads_fresh_record():
    manager, conn = manager_and_connection([[deepcopy(RECORD)]])
    settings = await manager.get_teleport_settings()
    assert settings.subnet_cidr == "192.168.2.1/24"
    assert conn.request.call_args.args[0].path == "/get/setting/teleport"


@pytest.mark.asyncio
async def test_get_without_record_is_empty_view():
    manager, _ = manager_and_connection([[]])
    settings = await manager.get_teleport_settings()
    assert settings.model_dump() == {"enabled": None, "subnet_cidr": None, "id": None, "site_id": None}


@pytest.mark.asyncio
async def test_prepare_reports_conflicts_without_writing():
    manager, conn = manager_and_connection([[deepcopy(RECORD)], deepcopy(NETWORKS)])
    current, updates, conflicts = await manager.prepare_teleport_settings_update({"subnet_cidr": "10.100.9.1/24"})
    assert current["subnet_cidr"] == "192.168.2.1/24"
    assert updates == {"subnet_cidr": "10.100.9.1/24"}
    assert conflicts == ["Default"]
    assert [call.args[0].method for call in conn.request.call_args_list] == ["get", "get"]


@pytest.mark.asyncio
async def test_full_record_write_preserves_other_fields_and_verifies():
    after = {**deepcopy(RECORD), "subnet_cidr": "10.201.0.1/24"}
    manager, conn = manager_and_connection([[deepcopy(RECORD)], deepcopy(NETWORKS), [], [after]])
    result = await manager.update_teleport_settings({"subnet_cidr": "10.201.0.1/24"})
    assert result.success is True
    assert result.mutation_applied is True
    assert result.persisted_fields == ("subnet_cidr",)
    assert result.unchanged_fields == ("enabled",)
    assert result.resource["subnet_cidr"] == "10.201.0.1/24"
    write = conn.request.call_args_list[2].args[0]
    assert write.method == "put"
    assert write.path == "/set/setting/teleport"
    assert write.data == after
    assert RECORD["subnet_cidr"] == "192.168.2.1/24"
    conn._invalidate_cache.assert_called_once_with("settings_teleport_default")


@pytest.mark.asyncio
async def test_noop_skips_overlap_check_and_write():
    manager, conn = manager_and_connection([[deepcopy(RECORD)]])
    result = await manager.update_teleport_settings({"subnet_cidr": "192.168.2.1/24"})
    assert result.success is True
    assert result.mutation_applied is False
    assert conn.request.await_count == 1


@pytest.mark.asyncio
async def test_overlapping_range_is_refused_before_write():
    manager, conn = manager_and_connection([[deepcopy(RECORD)], deepcopy(NETWORKS)])
    result = await manager.update_teleport_settings({"subnet_cidr": "10.110.0.1/24"})
    assert result.success is False
    assert result.mutation_applied is False
    assert result.error == "Teleport range overlaps configured network(s): Guests"
    assert conn.request.await_count == 2


@pytest.mark.asyncio
async def test_invalid_value_is_refused_before_any_request():
    manager, conn = manager_and_connection([])
    with pytest.raises(ValueError):
        await manager.update_teleport_settings({"subnet_cidr": "8.8.8.1/24"})
    conn.request.assert_not_awaited()
    conn.ensure_session_connected.assert_not_awaited()


@pytest.mark.asyncio
async def test_write_requires_session():
    manager, conn = manager_and_connection([])
    conn.ensure_session_connected = AsyncMock(return_value=False)
    with pytest.raises(RuntimeError, match="session authentication"):
        await manager.update_teleport_settings({"subnet_cidr": "10.201.0.1/24"})
    conn.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_record_is_refused():
    manager, conn = manager_and_connection([[]])
    with pytest.raises(RuntimeError, match="enable Teleport once"):
        await manager.update_teleport_settings({"subnet_cidr": "10.201.0.1/24"})
    assert conn.request.await_count == 1


@pytest.mark.asyncio
async def test_controller_rejection_is_reported_by_code():
    rejection = SettingsControllerRejection("api.err.InvalidPayload")
    manager, conn = manager_and_connection([[deepcopy(RECORD)], deepcopy(NETWORKS), rejection])
    result = await manager.update_teleport_settings({"subnet_cidr": "10.201.0.1/24"})
    assert result.success is False
    assert result.mutation_applied is False
    assert result.error == "Controller rejected Teleport settings update (api.err.InvalidPayload)"
    conn._invalidate_cache.assert_called_once()


@pytest.mark.asyncio
async def test_transport_failure_is_uncertain():
    manager, _ = manager_and_connection([[deepcopy(RECORD)], deepcopy(NETWORKS), RequestError("timeout")])
    result = await manager.update_teleport_settings({"subnet_cidr": "10.201.0.1/24"})
    assert result.success is False
    assert result.mutation_applied is None
    assert result.metadata["outcome_uncertain"] is True


@pytest.mark.asyncio
async def test_dropped_range_fails_verification():
    manager, _ = manager_and_connection([[deepcopy(RECORD)], deepcopy(NETWORKS), [], [deepcopy(RECORD)]])
    result = await manager.update_teleport_settings({"subnet_cidr": "10.201.0.1/24"})
    assert result.success is False
    assert result.dropped_fields == ("subnet_cidr",)


@pytest.mark.asyncio
async def test_enabled_flip_fails_verification():
    after = {**deepcopy(RECORD), "subnet_cidr": "10.201.0.1/24", "enabled": False}
    manager, _ = manager_and_connection([[deepcopy(RECORD)], deepcopy(NETWORKS), [], [after]])
    result = await manager.update_teleport_settings({"subnet_cidr": "10.201.0.1/24"})
    assert result.success is False
    assert result.coerced_fields == ("enabled",)
