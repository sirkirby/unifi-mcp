"""Tests for the MCP-direct and API action phases in scripts/live_smoke.py."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def test_live_smoke_setup_aborts_before_registration_when_authentication_fails(monkeypatch):
    import live_smoke

    connection_manager = SimpleNamespace(
        initialize=AsyncMock(return_value=False),
        last_connection_error="429: login attempt limit reached",
    )
    register_tools = AsyncMock()
    modules = {
        "unifi_network_mcp.main": SimpleNamespace(_original_tool_decorator=object()),
        "unifi_network_mcp.runtime": SimpleNamespace(
            server=object(), connection_manager=connection_manager, config=object()
        ),
        "unifi_network_mcp.bootstrap": SimpleNamespace(UNIFI_TOOL_REGISTRATION_MODE="lazy", logger=object()),
        "unifi_network_mcp.categories": SimpleNamespace(TOOL_MODULE_MAP={}, setup_lazy_loading=object()),
        "unifi_network_mcp.jobs": SimpleNamespace(start_async_tool=object(), get_job_status=object()),
        "unifi_network_mcp.tool_index": SimpleNamespace(tool_index_handler=object(), register_tool=object()),
        "unifi_mcp_shared.tool_registration": SimpleNamespace(register_tools_for_mode=register_tools),
    }
    monkeypatch.setattr(live_smoke, "configure_environment", lambda: None)
    monkeypatch.setattr(live_smoke.importlib, "import_module", modules.__getitem__)
    runner = live_smoke.LiveSmokeRunner("network", SimpleNamespace())

    with pytest.raises(ConnectionError, match="aborting before tool execution.*429"):
        asyncio.run(runner.setup())

    assert runner.report.connected is False
    assert [(record.tool, record.phase, record.status) for record in runner.report.records] == [
        ("__setup__", "setup", "failed")
    ]
    assert "connect or authenticate" in runner.report.records[0].error
    register_tools.assert_not_awaited()


def test_run_one_writes_setup_and_cleanup_failures_when_close_raises(monkeypatch, tmp_path):
    import live_smoke

    class FailingRunner:
        def __init__(self, server_key, _args):
            self.server_key = server_key
            self.report = live_smoke.SmokeReport(server=server_key, started_at="2026-01-01T00:00:00+00:00")

        async def setup(self):
            self.report.records.append(
                live_smoke.SmokeRecord(
                    tool="__setup__",
                    phase="setup",
                    status="failed",
                    success=False,
                    error="setup failed",
                )
            )
            raise ConnectionError("setup failed")

        async def close(self):
            raise RuntimeError("close failed")

    monkeypatch.setattr(live_smoke, "LiveSmokeRunner", FailingRunner)
    args = SimpleNamespace(server="network", report_dir=str(tmp_path))

    with pytest.raises(ConnectionError, match="setup failed"):
        asyncio.run(live_smoke.run_one(args))

    reports = list(tmp_path.glob("network-*.json"))
    assert len(reports) == 1
    payload = json.loads(reports[0].read_text())
    assert [(record["tool"], record["status"]) for record in payload["records"]] == [
        ("__setup__", "failed"),
        ("__cleanup__", "failed"),
    ]


def test_live_api_catalog_probe_reports_exact_parity(monkeypatch, tmp_path):
    import live_smoke

    catalog = {
        "actions": [
            {"name": "unifi_list_clients", "product": "network"},
            {"name": "protect_list_cameras", "product": "protect"},
            {"name": "access_list_doors", "product": "access"},
        ]
    }
    catalog_path = tmp_path / "action_catalog.json"
    catalog_path.write_text(json.dumps(catalog))
    monkeypatch.setattr(live_smoke, "API_ACTION_CATALOG", catalog_path)

    result = live_smoke._validate_api_action_catalog({"items": [{"name": item["name"]} for item in catalog["actions"]]})

    assert result["expected_count"] == 3
    assert result["actual_count"] == 3
    assert result["missing"] == []
    assert result["unexpected"] == []
    assert all(result["sentinels"].values())


def test_live_api_confirmation_preview_control_requires_safe_preview():
    import live_smoke

    response = {
        "success": True,
        "requires_confirmation": True,
        "tool": "unifi_reboot_device",
        "action": "update",
        "preview": {"proposed": {"mac_address": "00:00:00:00:00:00"}},
    }
    assert live_smoke._classify_confirmation_preview_control(
        200,
        response,
        expected_tool="unifi_reboot_device",
    ) == {"passed": True, "tool_returned": "unifi_reboot_device", "response": response}
    assert (
        live_smoke._classify_confirmation_preview_control(
            200,
            {"success": True},
            expected_tool="unifi_reboot_device",
        )["passed"]
        is False
    )
    assert (
        live_smoke._classify_confirmation_preview_control(
            200,
            {"success": False, "error": "tool 'unifi_reboot_device' requires confirm=true"},
            expected_tool="unifi_reboot_device",
        )["passed"]
        is False
    )
    assert (
        live_smoke._classify_confirmation_preview_control(
            200,
            {**response, "tool": "protect_reboot_camera"},
            expected_tool="unifi_reboot_device",
        )["passed"]
        is False
    )


def test_api_actions_have_no_baseline_failure_exemption():
    import live_smoke

    assert live_smoke._classify_api_action_result(True, True) == "pass"
    assert live_smoke._classify_api_action_result(False, True) == "regression"
    assert live_smoke._classify_api_action_result(None, True) == "regression"
    assert live_smoke._classify_api_action_result(True, False) == "regression"


def test_api_resource_parity_uses_public_network_mac_identity_and_complete_client_collection():
    import live_smoke

    client_sample = next(
        sample for sample in live_smoke.API_RESOURCES_SAMPLE if sample[1] == "/v1/sites/{site}/clients"
    )
    assert client_sample[4] == {"limit": 1000}
    assert live_smoke.API_RESOURCE_PARITY_ID_KEYS == {
        "/v1/sites/{site}/clients": ("mac",),
        "/v1/sites/{site}/devices": ("mac",),
    }

    resource_rows = [{"mac": "aa:bb:cc:dd:ee:ff"}]
    action_rows = [{"_id": "controller-object-id", "mac": "aa:bb:cc:dd:ee:ff"}]

    assert live_smoke._items_id_set(resource_rows, ("mac",)) == live_smoke._items_id_set(
        action_rows,
        ("mac",),
    )


def test_live_api_non_default_read_contract_requires_projection_limit_and_metadata():
    import live_smoke

    response = {
        "success": True,
        "data": [{"mac": "aa:bb", "connection_type": "Wireless"}],
        "meta": {
            "filter_type": "wireless",
            "search": "phone",
            "fields": "mac,connection_type",
            "limit": 1,
            "total_count": 2,
            "returned_count": 1,
        },
    }
    assert live_smoke._validate_api_read_contract_probe(
        response,
        expected_meta={
            "filter_type": "wireless",
            "search": "phone",
            "fields": "mac,connection_type",
            "limit": 1,
        },
        projected_fields={"mac", "connection_type"},
    ) == {"passed": True, "errors": []}

    broken = {
        **response,
        "data": [{"mac": "aa:bb", "name": "Phone"}, {"mac": "cc:dd"}],
        "meta": {**response["meta"], "limit": 100},
    }
    result = live_smoke._validate_api_read_contract_probe(
        broken,
        expected_meta={"limit": 1},
        projected_fields={"mac", "connection_type"},
    )
    assert result["passed"] is False
    assert result["errors"] == [
        "meta.limit expected 1, got 100",
        "data length 2 exceeds limit 1",
        "meta.returned_count expected 2, got 1",
        "data[0] contains fields outside projection: name",
    ]

    empty_positive = live_smoke._validate_api_read_contract_probe(
        {
            "success": True,
            "data": [],
            "meta": {"limit": 1, "returned_count": 0, "total_count": 0},
        },
        expected_meta={"limit": 1},
        projected_fields={"mac"},
        require_non_empty=True,
    )
    assert empty_positive == {"passed": False, "errors": ["positive control returned no rows"]}


def test_live_smoke_known_controller_issue_matches_exact_error_code():
    import live_smoke

    runner = live_smoke.LiveSmokeRunner.__new__(live_smoke.LiveSmokeRunner)
    assert runner.expected_known_controller_issue(
        "access_get_activity_summary",
        "Proxy request failed: API code -3 CODE_SYSTEM_ERROR GET https://example.test",
    )
    assert not runner.expected_known_controller_issue(
        "access_get_activity_summary",
        "Proxy request failed: API code -30 CODE_SYSTEM_ERROR GET https://example.test",
    )


def test_live_smoke_known_firewall_policy_rejection_requires_controller_code():
    import live_smoke

    runner = live_smoke.LiveSmokeRunner.__new__(live_smoke.LiveSmokeRunner)
    assert runner.expected_known_controller_issue(
        "unifi_create_firewall_policy",
        (
            "Failed to create firewall policy: api.err.FirewallPolicyCreateRespondTrafficPolicyNotAllowed "
            "Firewall policy create respond traffic not allowed"
        ),
    )
    assert not runner.expected_known_controller_issue(
        "unifi_create_firewall_policy",
        "Failed to create firewall policy: Firewall policy create respond traffic not allowed",
    )


def test_live_smoke_seeds_protect_capability_preview_dependencies():
    import live_smoke

    runner = live_smoke.LiveSmokeRunner.__new__(live_smoke.LiveSmokeRunner)
    runner.args = SimpleNamespace(tool=["protect_update_chime"])
    runner.manifest = {"tools": [{"name": "protect_update_chime"}, {"name": "protect_list_chimes"}]}
    assert runner.preview_seed_tool_names() == {"protect_list_chimes"}


def test_live_smoke_protect_capability_preview_args_from_seeded_inventory():
    import live_smoke

    runner = live_smoke.LiveSmokeRunner.__new__(live_smoke.LiveSmokeRunner)
    runner.cache = live_smoke.ResourceCache()
    runner.connection_manager = SimpleNamespace(has_api_key=True)
    runner.cache.remember(
        "protect_list_sensors",
        {"success": True, "data": {"sensors": [{"id": "sensor-1", "name": "Garage"}]}},
    )
    runner.cache.remember(
        "protect_list_chimes",
        {
            "success": True,
            "data": {
                "chimes": [
                    {
                        "id": "chime-1",
                        "name": "Doorbell Chime",
                        "ring_settings": [{"camera_id": "camera-1", "volume": 75, "repeat_times": 2}],
                    }
                ]
            },
        },
    )
    runner.cache.remember(
        "protect_list_viewers",
        {"success": True, "data": {"viewers": [{"id": "viewer-1", "name": "Lobby Viewer"}]}},
    )
    assert runner.preview_args("protect_update_sensor_settings") == (
        {"sensor_id": "sensor-1", "settings": {"name": "Garage"}},
        "",
    )
    assert runner.preview_args("protect_update_chime") == (
        {"chime_id": "chime-1", "settings": {"camera_id": "camera-1", "volume": 75}},
        "",
    )
    assert runner.preview_args("protect_update_viewer") == (
        {"viewer_id": "viewer-1", "settings": {"name": "Lobby Viewer"}},
        "",
    )


def test_summarize_failed_applied_create_retains_cleanup_id() -> None:
    import live_smoke

    summary = live_smoke.summarize_payload(
        {
            "success": False,
            "mutation_applied": True,
            "network_id": "network-created-but-coerced",
            "details_after_attempt": {"_id": "network-created-but-coerced"},
            "error": "purpose was coerced",
        }
    )

    assert summary["resource_id"] == "network-created-but-coerced"
    assert summary["error"] == "purpose was coerced"


def test_network_lifecycle_creates_updates_reads_and_deletes_disposable_vlan() -> None:
    import live_smoke

    runner = object.__new__(live_smoke.LiveSmokeRunner)
    cache = SimpleNamespace(items_from_tool=lambda *_args: [{"vlan": 3999}], by_tool={})
    runner.cache = cache
    runner.report = SimpleNamespace(created_resources=[], cleaned_resources=[], records=[])
    runner.server_key = "network"
    calls: list[tuple[str, dict, str]] = []

    async def call(tool: str, args: dict, phase: str):
        calls.append((tool, args, phase))
        if tool == "unifi_get_network_details":
            cache.by_tool[tool] = {
                "details": {
                    "name": calls[-2][1]["update_data"]["name"],
                    "enabled": False,
                    "purpose": "vlan-only",
                    "vlan": 3998,
                }
            }
        summary = {"resource_id": "network-smoke-1"} if tool == "unifi_create_network" else {}
        return SimpleNamespace(summary=summary, success=True)

    runner.call = call
    runner.skip = lambda *_args: None

    asyncio.run(runner.lifecycle_network_network())

    assert [tool for tool, _args, _phase in calls] == [
        "unifi_create_network",
        "unifi_update_network",
        "unifi_get_network_details",
        "unifi_delete_network",
    ]
    create_args = calls[0][1]["network_data"]
    assert create_args["purpose"] == "vlan-only"
    assert create_args["enabled"] is False
    assert create_args["vlan"] == 3998
    assert calls[-1][1] == {"network_id": "network-smoke-1", "confirm": True}
    assert runner.report.created_resources == [
        {"type": "network", "id": "network-smoke-1", "name": create_args["name"]}
    ]
    assert runner.report.cleaned_resources == runner.report.created_resources


def test_failed_applied_network_create_still_runs_cleanup() -> None:
    import live_smoke

    runner = object.__new__(live_smoke.LiveSmokeRunner)
    runner.cache = SimpleNamespace(items_from_tool=lambda *_args: [])
    runner.report = SimpleNamespace(created_resources=[], cleaned_resources=[], records=[])
    runner.server_key = "network"
    calls: list[str] = []

    async def call(tool: str, _args: dict, _phase: str):
        calls.append(tool)
        if tool == "unifi_create_network":
            raw = {
                "success": False,
                "mutation_applied": True,
                "network_id": "network-coerced-1",
                "error": "field was coerced",
            }
            return SimpleNamespace(summary=live_smoke.summarize_payload(raw), success=False)
        return SimpleNamespace(summary={}, success=True)

    runner.call = call
    runner.skip = lambda *_args: None

    asyncio.run(runner.lifecycle_network_network())

    assert calls == ["unifi_create_network", "unifi_delete_network"]
    assert runner.report.cleaned_resources[0]["id"] == "network-coerced-1"
    assert any(record.status == "failed" for record in runner.report.records)


def test_ambiguous_applied_network_create_is_reported_as_cleanup_failure() -> None:
    import live_smoke

    runner = object.__new__(live_smoke.LiveSmokeRunner)
    created_name: str | None = None

    def cached_items(tool: str, _key: str):
        if tool == "unifi_list_networks" and created_name:
            return [{"_id": "net-1", "name": created_name}, {"_id": "net-2", "name": created_name}]
        return []

    runner.cache = SimpleNamespace(items_from_tool=cached_items)
    runner.report = SimpleNamespace(created_resources=[], cleaned_resources=[], records=[])
    runner.server_key = "network"
    skipped: list[str] = []

    async def call(tool: str, args: dict, _phase: str):
        nonlocal created_name
        if tool == "unifi_create_network":
            created_name = args["network_data"]["name"]
            raw = {"success": False, "mutation_applied": True, "error": "read-back malformed"}
            return SimpleNamespace(summary=live_smoke.summarize_payload(raw), success=False)
        return SimpleNamespace(summary={}, success=True)

    runner.call = call
    runner.skip = lambda tool, *_args: skipped.append(tool)

    asyncio.run(runner.lifecycle_network_network())

    assert "unifi_delete_network" in skipped
    assert any(record.tool == "unifi_delete_network" and record.status == "failed" for record in runner.report.records)


def test_wlan_lifecycle_reads_back_and_cleans_up_disposable_wlan() -> None:
    import live_smoke

    runner = object.__new__(live_smoke.LiveSmokeRunner)
    cache = SimpleNamespace(id_from_tool=lambda *_args: "ap-group-1", by_tool={})
    runner.cache = cache
    runner.report = SimpleNamespace(created_resources=[], cleaned_resources=[], records=[])
    runner.server_key = "network"
    calls: list[tuple[str, dict, str]] = []

    async def call(tool: str, args: dict, phase: str):
        calls.append((tool, args, phase))
        if tool == "unifi_get_wlan_details":
            cache.by_tool[tool] = {
                "details": {
                    "name": calls[0][1]["wlan_data"]["name"],
                    "enabled": False,
                    "security": "open",
                    "hide_ssid": False,
                    "minrate_ng_data_rate_kbps": 6000,
                }
            }
        summary = {"resource_id": "wlan-smoke-1"} if tool == "unifi_create_wlan" else {}
        return SimpleNamespace(summary=summary, success=True)

    runner.call = call
    runner.skip = lambda *_args: None

    asyncio.run(runner.lifecycle_network_wlan())

    assert [tool for tool, _args, _phase in calls] == [
        "unifi_create_wlan",
        "unifi_update_wlan",
        "unifi_update_wlan",
        "unifi_get_wlan_details",
        "unifi_delete_wlan",
    ]
    assert calls[0][1]["wlan_data"]["enabled"] is False
    assert calls[-1][1] == {"wlan_id": "wlan-smoke-1", "confirm": True}
    assert runner.report.cleaned_resources == runner.report.created_resources


def test_live_smoke_protect_api_key_preview_skip_when_missing():
    import live_smoke

    runner = live_smoke.LiveSmokeRunner.__new__(live_smoke.LiveSmokeRunner)
    runner.cache = live_smoke.ResourceCache()
    runner.connection_manager = SimpleNamespace(has_api_key=False)
    runner.cache.remember(
        "protect_list_sensors",
        {"success": True, "data": {"sensors": [{"id": "sensor-1", "name": "Garage"}]}},
    )
    assert runner.preview_args("protect_update_sensor_settings") == (
        None,
        "requires UNIFI_PROTECT_API_KEY or UNIFI_API_KEY",
    )
