"""Self-tests for scripts/live_api_smoke.py."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Make scripts/ importable
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))


def test_load_env_parses_a_synthetic_dotenv(tmp_path, monkeypatch):
    """load_env() parses comments, quoted values, and KEY=VALUE pairs.

    Uses a synthetic .env in tmp_path so this works in CI (where the real
    repo-root .env is absent) and locally (without depending on actual creds).
    """
    import live_api_smoke

    env_file = tmp_path / ".env"
    env_file.write_text("# a comment\n\nPLAIN=value1\nQUOTED=\"value with spaces\"\nSINGLE='single'\n")
    monkeypatch.setattr(live_api_smoke, "REPO_ROOT", tmp_path)

    env = live_api_smoke.load_env()
    assert env == {"PLAIN": "value1", "QUOTED": "value with spaces", "SINGLE": "single"}


def test_load_env_raises_when_dotenv_absent(tmp_path, monkeypatch):
    """load_env() raises SystemExit if .env is missing — preserves the existing contract."""
    import live_api_smoke

    monkeypatch.setattr(live_api_smoke, "REPO_ROOT", tmp_path)
    with pytest.raises(SystemExit, match=".env not found"):
        live_api_smoke.load_env()


def test_assertion_dataclass_serializes():
    from dataclasses import asdict

    from live_api_smoke import Assertion

    a = Assertion(name="x", product="network", surface="rest")
    d = asdict(a)
    assert d["name"] == "x"
    assert d["passed"] is False


def test_report_counters():
    from live_api_smoke import Assertion, Report

    r = Report()
    r.assertions.append(Assertion(name="ok", product="x", surface="rest", passed=True))
    r.assertions.append(Assertion(name="bad", product="x", surface="rest", passed=False))
    assert r.total == 2
    assert r.passed == 1
    assert r.failed == 1


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


def test_live_smoke_known_visitor_endpoint_404_requires_full_signature():
    import live_smoke

    runner = live_smoke.LiveSmokeRunner.__new__(live_smoke.LiveSmokeRunner)

    assert runner.expected_known_controller_issue(
        "access_create_visitor",
        (
            "Failed to create visitor: Proxy request failed: HTTP 404 POST "
            "https://127.0.0.1:11444/proxy/access/api/v2/visitors "
            '{"code":404,"codeS":"CODE_NOT_FOUND","msg":"The API was not found.",'
            '"error":"you entered no-man zone"}'
        ),
    )
    assert not runner.expected_known_controller_issue(
        "access_create_visitor",
        (
            "Failed to create visitor: Proxy request failed: HTTP 404 POST "
            "https://127.0.0.1:11444/proxy/access/api/v2/visitor-groups "
            '{"code":404,"codeS":"CODE_NOT_FOUND","msg":"The API was not found.",'
            '"error":"you entered no-man zone"}'
        ),
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
    runner.manifest = {
        "tools": [
            {"name": "protect_update_chime"},
            {"name": "protect_list_chimes"},
        ]
    }

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
