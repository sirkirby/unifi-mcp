"""Verified singleton writes reject unsafe inputs and retain controller-owned data."""

import copy
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.network.managers.system_manager import SystemManager
from unifi_core.network.models.threat_management import (
    merge_threat_management_update,
)

IPS = {
    "_id": "ips-record",
    "key": "ips",
    "ips_mode": "ips",
    "advanced_filtering_preference": "manual",
    "memory_optimized": True,
    "enabled_categories": ["malware", "botnet"],
    "enabled_networks": ["network-id"],
    "utm_token": "private-canary",
    "unknown": {"preserved": True},
}
DPI = {"_id": "dpi-record", "key": "dpi", "enabled": True, "fingerprintingEnabled": True}
CATALOG = [{"value": "malware"}, {"value": "botnet"}]


def manager_with(responses):
    connection = MagicMock()
    connection.site = "default"
    connection.ensure_session_connected = AsyncMock(return_value=True)
    connection.request = AsyncMock(side_effect=responses)
    return SystemManager(connection), connection


@pytest.mark.parametrize(
    "fields",
    [
        {"ips_mode": "bogus"},
        {"ips_mode": None},
        {"enabled_categories": ["x", "x"]},
        {"enabled_categories": [1]},
        {"enabled_categories": None},
        {"enabled_categories": [""]},
        {"traffic_identification_enabled": 1},
        {"device_fingerprinting_enabled": "false"},
        {"utm_token": "secret"},
        {"enabled_networks": []},
        {"ips_mode": "ids", "traffic_identification_enabled": False},
    ],
)
@pytest.mark.asyncio
async def test_invalid_request_never_reaches_controller(fields):
    manager, conn = manager_with([])
    with pytest.raises(ValueError):
        await manager.update_threat_management_settings(fields)
    conn.request.assert_not_awaited()
    conn.ensure_session_connected.assert_not_awaited()


def test_mode_effects_are_explicit():
    disabled = merge_threat_management_update({"ips_mode": "disabled"}, IPS)
    assert disabled == {"ips_mode": "disabled", "advanced_filtering_preference": "disabled", "enabled_categories": []}
    manual = merge_threat_management_update(
        {"enabled_categories": ["malware"]}, {**IPS, "advanced_filtering_preference": "auto"}, {"malware"}
    )
    assert manual["advanced_filtering_preference"] == "manual"
    with pytest.raises(ValueError):
        merge_threat_management_update({"ips_mode": "ids"}, {**IPS, "enabled_networks": []}, {"malware", "botnet"})
    with pytest.raises(ValueError):
        merge_threat_management_update({"enabled_categories": []}, IPS, {"malware"})
    with pytest.raises(ValueError):
        merge_threat_management_update({"enabled_categories": ["unknown"]}, IPS, {"malware"})


@pytest.mark.asyncio
async def test_empty_update_is_noop_without_io():
    manager, conn = manager_with([])
    result = await manager.update_threat_management_settings({})
    assert result.success and result.mutation_applied is False
    conn.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_fresh_merge_preserves_unknown_secrets_and_networks_without_output_leak():
    before = copy.deepcopy(IPS)
    after = {**IPS, "enabled_categories": ["malware"]}
    manager, conn = manager_with([[before], CATALOG, [], [after]])
    result = await manager.update_threat_management_settings({"enabled_categories": ["malware"]})
    calls = conn.request.await_args_list
    assert [call.args[0].path for call in calls] == [
        "/get/setting/ips",
        "/settings/ips/available-categories?memoryOptimized=true",
        "/set/setting/ips",
        "/get/setting/ips",
    ]
    write = calls[2].args[0]
    assert write.method == "post"
    assert write.data == after
    assert before == IPS
    assert result.success and result.mutation_applied is True
    assert result.persisted_fields == ("enabled_categories",)
    assert "private-canary" not in json.dumps(result.to_dict())
    assert "unknown" not in result.resource
    conn._invalidate_cache.assert_called_once_with("settings_ips_default")
    conn.get_cached.assert_not_called()


@pytest.mark.asyncio
async def test_preview_has_derived_effects_and_no_write():
    manager, conn = manager_with([[IPS]])
    result = await manager.preview_threat_management_settings({"ips_mode": "disabled"})
    assert result["current"]["enabled"] is True
    assert result["after"]["enabled"] is False
    assert result["after"]["advanced_filtering_preference"] == "disabled"
    assert result["after"]["enabled_categories"] == []
    assert conn.request.await_count == 1
    assert "private-canary" not in json.dumps(result)


@pytest.mark.asyncio
async def test_dpi_single_endpoint_and_unmentioned_flag_preserved():
    after = {**DPI, "fingerprintingEnabled": False}
    manager, conn = manager_with([[DPI], [], [after]])
    result = await manager.update_threat_management_settings({"device_fingerprinting_enabled": False})
    assert conn.request.await_args_list[1].args[0].data == after
    assert result.success and result.persisted_fields == ("device_fingerprinting_enabled",)
    assert result.resource["traffic_identification_enabled"] is True


@pytest.mark.parametrize("after,field", [(IPS, "dropped_fields"), ({**IPS, "ips_mode": "ipsInline"}, "coerced_fields")])
@pytest.mark.asyncio
async def test_readback_classifies_dropped_and_coerced(after, field):
    manager, conn = manager_with([[IPS], CATALOG, [], [after]])
    result = await manager.update_threat_management_settings({"ips_mode": "ids"})
    assert not result.success and result.mutation_applied is True
    assert "ips_mode" in getattr(result, field)
    assert conn.request.await_count == 4


@pytest.mark.parametrize("failure_index", [0, 1, 2, 3])
@pytest.mark.asyncio
async def test_failure_privacy_and_uncertain_write(failure_index, caplog):
    responses = [[IPS], CATALOG, [], [IPS]]
    responses[failure_index] = RuntimeError("private-canary")
    manager, conn = manager_with(responses)
    if failure_index < 2:
        with pytest.raises(RuntimeError) as exc:
            await manager.update_threat_management_settings({"ips_mode": "ids"})
        assert "private-canary" not in str(exc.value)
        assert exc.value.__suppress_context__
    else:
        result = await manager.update_threat_management_settings({"ips_mode": "ids"})
        assert not result.success and result.mutation_applied is None
        assert result.metadata["outcome_uncertain"]
        assert "private-canary" not in json.dumps(result.to_dict())
    assert "private-canary" not in caplog.text
    assert conn.request.await_count == failure_index + 1


@pytest.mark.asyncio
async def test_missing_session_blocks_all_requests():
    manager, conn = manager_with([])
    conn.ensure_session_connected.return_value = False
    with pytest.raises(RuntimeError, match="session authentication"):
        await manager.update_threat_management_settings({"ips_mode": "ids"})
    conn.request.assert_not_awaited()


@pytest.mark.parametrize("catalog", [[], {}, [{}], [{"value": 1}]])
@pytest.mark.asyncio
async def test_malformed_catalog_fails_closed(catalog):
    manager, conn = manager_with([[IPS], catalog])
    with pytest.raises(RuntimeError, match="catalog support"):
        await manager.update_threat_management_settings({"ips_mode": "ids"})
    assert conn.request.await_count == 2


@pytest.mark.asyncio
async def test_absent_fingerprinting_feature_is_rejected():
    manager, conn = manager_with([[{"_id": "dpi", "enabled": True}]])
    with pytest.raises(ValueError, match="unavailable"):
        await manager.update_threat_management_settings({"device_fingerprinting_enabled": False})
    assert conn.request.await_count == 1


def test_inline_mode_preservation_only_and_enabling_from_disabled():
    with pytest.raises(ValueError, match="ipsInline can only"):
        merge_threat_management_update({"ips_mode": "ipsInline"}, IPS, {"malware", "botnet"})
    assert (
        merge_threat_management_update(
            {"ips_mode": "ipsInline"}, {**IPS, "ips_mode": "ipsInline"}, {"malware", "botnet"}
        )["ips_mode"]
        == "ipsInline"
    )
    disabled = {**IPS, "ips_mode": "disabled", "advanced_filtering_preference": "disabled", "enabled_categories": []}
    with pytest.raises(ValueError, match="nonempty"):
        merge_threat_management_update({"ips_mode": "ids"}, disabled, {"malware"})
    enabled = merge_threat_management_update(
        {"ips_mode": "ids", "enabled_categories": ["malware"]}, disabled, {"malware"}
    )
    assert enabled["advanced_filtering_preference"] == "manual"
    assert (
        merge_threat_management_update(
            {"ips_mode": "ids"}, {**IPS, "advanced_filtering_preference": None}, {"malware", "botnet"}
        )["advanced_filtering_preference"]
        == "manual"
    )


@pytest.mark.asyncio
async def test_controller_category_order_is_semantically_equivalent():
    before = {**IPS, "enabled_categories": ["malware"]}
    after = {**IPS, "enabled_categories": ["botnet", "malware"]}
    manager, conn = manager_with([[before], CATALOG, [], [after]])
    result = await manager.update_threat_management_settings({"enabled_categories": ["malware", "botnet"]})
    assert result.success
    assert result.resource["enabled_categories"] == ["botnet", "malware"]


@pytest.mark.asyncio
async def test_auto_category_recomputation_is_not_requested_but_network_scope_is_guarded():
    before = {**IPS, "advanced_filtering_preference": "auto"}
    after = {**before, "ips_mode": "ids", "enabled_categories": ["malware"]}
    manager, _ = manager_with([[before], CATALOG, [], [after]])
    result = await manager.update_threat_management_settings({"ips_mode": "ids"})
    assert result.success
    assert "enabled_categories" not in result.unchanged_fields
    manager, _ = manager_with([[before], CATALOG, [], [{**after, "enabled_networks": []}]])
    result = await manager.update_threat_management_settings({"ips_mode": "ids"})
    assert not result.success and "enabled_networks" in result.coerced_fields
    assert result.metadata["collateral_changed_fields"] == ["enabled_networks"]
    assert "before another update" in result.error


@pytest.mark.asyncio
async def test_apply_refreshes_state_after_preview():
    changed = {**DPI, "unrelated_controller_field": "preserved-new-value"}
    after = {**changed, "fingerprintingEnabled": False}
    manager, conn = manager_with([[DPI], [changed], [], [after]])
    await manager.preview_threat_management_settings({"device_fingerprinting_enabled": False})
    result = await manager.update_threat_management_settings({"device_fingerprinting_enabled": False})
    assert result.success
    assert conn.request.await_args_list[2].args[0].data == after


@pytest.mark.asyncio
async def test_controller_rejection_is_known_failure_without_retry(caplog):
    from unifi_core.network.managers.connection_manager import SettingsControllerRejection

    manager, conn = manager_with([[IPS], CATALOG, SettingsControllerRejection("api.err.UnsupportedIpsCategories")])
    result = await manager.update_threat_management_settings({"ips_mode": "ids"})
    assert not result.success and result.mutation_applied is False
    assert "api.err.UnsupportedIpsCategories" in result.error
    assert conn.request.await_count == 3
    conn._invalidate_cache.assert_called_once()
