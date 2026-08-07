"""Tests for the MCP-direct and API action phases in scripts/live_smoke.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


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


def test_live_api_confirmation_negative_control_requires_interlock_error():
    import live_smoke

    assert live_smoke._classify_confirmation_negative_control(
        200,
        {"success": False, "error": "tool 'unifi_reboot_device' requires confirm=true"},
    ) == {"passed": True, "error": "tool 'unifi_reboot_device' requires confirm=true"}
    assert live_smoke._classify_confirmation_negative_control(200, {"success": True})["passed"] is False
    assert (
        live_smoke._classify_confirmation_negative_control(200, {"success": False, "error": "device not found"})[
            "passed"
        ]
        is False
    )


def test_api_actions_have_no_baseline_failure_exemption():
    import live_smoke

    assert live_smoke._classify_api_action_result(True, True) == "pass"
    assert live_smoke._classify_api_action_result(False, True) == "regression"
    assert live_smoke._classify_api_action_result(None, True) == "regression"
    assert live_smoke._classify_api_action_result(True, False) == "regression"


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
