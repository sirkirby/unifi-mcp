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


@pytest.fixture
def support_payload():
    return {
        "success": True,
        "data": {
            "generated_at": "2026-01-01T00:00:00Z",
            "product": "network",
            "server": {
                "package": "unifi-network-mcp",
                "version": "0.30.0",
                "tool": "unifi_get_support_bundle",
                "feature_flags": ["response_redaction_disabled"],
            },
            "runtime": {
                "python_version": "3.13.0",
                "os_family": "linux",
                "architecture": "x86_64",
                "transports": ["stdio"],
                "registration_mode": "lazy",
                "content_mode": "dual",
                "manifest_tool_count": 1,
                "manifest_generator": "scripts/generate_tool_manifest.py",
            },
            "dependencies": [],
            "controller": {"status": "available", "api_surface": "controller_v2"},
            "connection": {
                "initialized": True,
                "connected": True,
                "tls_verification_enabled": True,
                "last_attempt": {"status": "succeeded"},
                "capabilities": {
                    "product": "network",
                    "session_available": True,
                    "integration_api_key_configured": False,
                    "controller_type": "proxy",
                    "reconnect_circuit": "closed",
                },
            },
            "probe": {"probe": "summary", "status": "available"},
            "sanitization": {
                "values_suppressed": False,
                "dynamic_keys_suppressed": False,
                "errors_normalized": True,
                "variants_truncated": False,
                "nodes_truncated": False,
                "bytes_truncated": False,
            },
        },
    }


def test_support_accepts_closed_bundle_and_exact_plugin_version(support_payload):
    import support_smoke

    assert support_smoke.validate_bundle(support_payload, "network", "lazy", "summary", set(), "0.30.0") > 0


@pytest.mark.parametrize(
    "section,key,value,code",
    [
        ("connection", "connected", False, "connected"),
        ("runtime", "registration_mode", "eager", "registration_mode"),
        ("runtime", "content_mode", "json", "adaptive_content_mode"),
        ("runtime", "content_mode", "text", "adaptive_content_mode"),
        ("server", "version", "0.29.8", "plugin_package_version"),
        ("server", "feature_flags", [], "redaction_override_exercised"),
        ("server", "unexpected", "private", "bundle_schema"),
    ],
)
def test_support_rejects_contract_regressions(support_payload, section, key, value, code):
    import support_smoke

    support_payload["data"][section][key] = value
    with pytest.raises(support_smoke.SupportSmokeError, match=code):
        support_smoke.validate_bundle(support_payload, "network", "lazy", "summary", set(), "0.30.0")


def test_support_checks_entire_envelope_size_and_canaries(support_payload):
    import support_smoke

    support_payload["extra"] = "x" * 32768
    with pytest.raises(support_smoke.SupportSmokeError, match="envelope_size"):
        support_smoke.validate_bundle(support_payload, "network", "lazy", "summary", set(), None)
    for canary in support_smoke.private_canaries({"UNIFI_HOST": "private.example", "UNIFI_PASSWORD": "secret-value"}):
        support_payload["extra"] = canary.decode()
        with pytest.raises(support_smoke.SupportSmokeError, match="private_canary"):
            support_smoke.validate_bundle(support_payload, "network", "lazy", "summary", {canary}, None)


def test_support_environment_never_mutates_parent_and_overrides_bypass(monkeypatch, tmp_path):
    import support_smoke

    monkeypatch.setenv("UNIFI_NETWORK_TOOL_PERMISSION_MODE", "bypass")
    (tmp_path / ".env").write_text("UNIFI_MCP_HTTP_ENABLED=true\nUNIFI_NETWORK_REDACT_SENSITIVE_FIELDS=true\n")
    env = support_smoke.support_environment(tmp_path, "meta_only")
    assert env["UNIFI_NETWORK_TOOL_PERMISSION_MODE"] == "confirm"
    assert env["UNIFI_MCP_HTTP_ENABLED"] == "false"
    assert env["UNIFI_NETWORK_REDACT_SENSITIVE_FIELDS"] == "false"
    assert env["UNIFI_TOOL_REGISTRATION_MODE"] == "meta_only"
    assert support_smoke.os.environ["UNIFI_NETWORK_TOOL_PERMISSION_MODE"] == "bypass"


@pytest.mark.parametrize("secret", ['quoted"password', r"back\slash", "café-秘密", "unifi"])
def test_support_canaries_handle_json_escaping_without_public_package_collisions(support_payload, secret):
    import support_smoke

    canaries = support_smoke.private_canaries({"UNIFI_PASSWORD": secret})
    assert support_smoke.validate_bundle(support_payload, "network", "lazy", "summary", canaries, "0.30.0") > 0
    for encoded in (secret, json.dumps(secret), json.dumps({"content": [{"text": json.dumps({"leak": secret})}]})):
        assert support_smoke.contains_private_canary(encoded, canaries)
    support_payload["extra"] = secret
    with pytest.raises(support_smoke.SupportSmokeError, match="private_canary"):
        support_smoke.validate_bundle(support_payload, "network", "lazy", "summary", canaries, None)


@pytest.mark.parametrize("secret", ["x", "xy", "xyz"])
def test_support_short_canaries_fail_closed_before_server_start(monkeypatch, tmp_path, secret):
    from unittest.mock import Mock

    import support_smoke

    monkeypatch.setenv("UNIFI_USERNAME", secret)
    start = Mock()
    monkeypatch.setattr(support_smoke, "stdio_client", start)
    with pytest.raises(support_smoke.SupportSmokeError, match="short_private_canary"):
        support_smoke.private_canaries({"UNIFI_USERNAME": secret})
    assert support_smoke.private_canaries({"UNIFI_USERNAME": ""}) == set()
    assert asyncio.run(support_smoke.run_support_phase("network", tmp_path))["success"] is False
    start.assert_not_called()


@pytest.mark.parametrize("form", ["raw", "sha256", "base64", "json"])
def test_support_matrix_rejects_private_stderr_even_after_success(monkeypatch, tmp_path, capsys, form):
    import base64
    import hashlib
    from contextlib import asynccontextmanager

    import support_smoke

    secret = 'private"password'
    monkeypatch.setenv("UNIFI_PASSWORD", secret)
    log = {
        "raw": secret,
        "sha256": hashlib.sha256(secret.encode()).hexdigest(),
        "base64": base64.b64encode(secret.encode()).decode(),
        "json": json.dumps({"password": secret}),
    }[form]

    @asynccontextmanager
    async def transport(parameters, *, errlog):
        errlog.write(log)
        yield (None, None)

    @asynccontextmanager
    async def session(*args, **kwargs):
        yield None

    monkeypatch.setattr(support_smoke, "stdio_client", transport)
    monkeypatch.setattr(support_smoke, "ClientSession", session)
    monkeypatch.setattr(support_smoke, "exercise_session", AsyncMock(return_value={"status": "passed"}))
    report = asyncio.run(support_smoke.run_support_phase("all", tmp_path))
    assert report == {"success": False, "records": [{"product": "network", "mode": "lazy", "status": "failed"}]}
    assert log not in capsys.readouterr().out + json.dumps(report)


@pytest.mark.parametrize("probe_leaks", [False, True])
def test_support_log_boundary_excludes_startup_but_checks_probe_output(monkeypatch, tmp_path, probe_leaks):
    from contextlib import asynccontextmanager

    import support_smoke

    monkeypatch.setenv("UNIFI_HOST", "private.example")
    captured = []

    @asynccontextmanager
    async def transport(parameters, *, errlog):
        errlog.write("Ordinary startup: private.example\n")
        captured.append(errlog)
        yield (None, None)

    @asynccontextmanager
    async def session(*args, **kwargs):
        yield None

    async def exercise(*args, before_probes):
        before_probes()
        if probe_leaks:
            captured[-1].write("Support probe: private.example\n")
        return {"status": "passed"}

    monkeypatch.setattr(support_smoke, "stdio_client", transport)
    monkeypatch.setattr(support_smoke, "ClientSession", session)
    monkeypatch.setattr(support_smoke, "exercise_session", exercise)
    assert asyncio.run(support_smoke.run_support_phase("network", tmp_path))["success"] is not probe_leaks


def _support_client(payload, *, structured=False):
    import copy

    connectivity = copy.deepcopy(payload)
    connectivity["data"]["probe"] = {
        "probe": "connectivity",
        "status": "available",
        "outcome": "success",
        "duration_bucket": "under_100ms",
    }
    outputs = [
        payload,
        connectivity,
        {"success": False, "error": "Failed to generate support bundle: this live probe is in cooldown."},
        {"success": False, "error": "Failed to generate support bundle: invalid probe."},
        payload,
    ]

    def result(item):
        return SimpleNamespace(
            is_error=False,
            content=[SimpleNamespace(text="Human-readable compact summary" if structured else json.dumps(item))],
            structured_content=item if structured else None,
            model_dump_json=lambda: json.dumps(item),
        )

    tool = SimpleNamespace(
        name="unifi_get_support_bundle",
        annotations=SimpleNamespace(read_only_hint=True),
        input_schema={"properties": {"probe": {"enum": ["summary", "connectivity", "resource_shape"]}}},
    )
    client = SimpleNamespace(
        initialize=AsyncMock(),
        list_tools=AsyncMock(return_value=SimpleNamespace(tools=[tool])),
        call_tool=AsyncMock(side_effect=[result(item) for item in outputs]),
    )
    return client


@pytest.mark.parametrize("structured", [False, True])
def test_support_session_exercises_exact_read_only_matrix(support_payload, structured):
    import support_smoke

    client = _support_client(support_payload, structured=structured)

    def before_probes():
        client.initialize.assert_awaited_once()
        client.list_tools.assert_awaited_once()
        client.call_tool.assert_not_awaited()

    report = asyncio.run(support_smoke.exercise_session(client, "network", "lazy", {}, "0.30.0", before_probes))
    assert report["status"] == "passed"
    assert [call.args for call in client.call_tool.await_args_list] == [
        ("unifi_get_support_bundle", {"probe": probe})
        for probe in ("summary", "connectivity", "connectivity", support_smoke.INVALID_PROBE, "summary")
    ]
    assert "0.30.0" not in json.dumps(report)


@pytest.mark.parametrize("failure", ["missing_tool", "connectivity", "cooldown", "invalid_echo"])
def test_support_session_cannot_pass_missing_checks(support_payload, failure):
    import support_smoke

    client = _support_client(support_payload)
    if failure == "missing_tool":
        client.list_tools.return_value.tools = []
    else:
        items = list(client.call_tool.side_effect)
        index = {"connectivity": 1, "cooldown": 2, "invalid_echo": 3}[failure]
        payload = (
            {"success": True} if failure != "invalid_echo" else {"success": False, "error": support_smoke.INVALID_PROBE}
        )
        items[index] = SimpleNamespace(
            is_error=False,
            content=[SimpleNamespace(text=json.dumps(payload))],
            model_dump_json=lambda: json.dumps(payload),
        )
        client.call_tool.side_effect = items
    with pytest.raises((support_smoke.SupportSmokeError, ValueError)):
        asyncio.run(support_smoke.exercise_session(client, "network", "lazy", {}, "0.30.0"))


def test_support_matrix_stops_on_failure_without_echoing_secrets(monkeypatch, tmp_path, capsys):
    from contextlib import asynccontextmanager

    import support_smoke

    attempts = []

    @asynccontextmanager
    async def failed_transport(parameters, **kwargs):
        attempts.append(parameters)
        raise RuntimeError("private-password and controller address")
        yield  # pragma: no cover

    monkeypatch.setattr(support_smoke, "stdio_client", failed_transport)
    report = asyncio.run(support_smoke.run_support_phase("all", tmp_path))
    assert report == {"success": False, "records": [{"product": "network", "mode": "lazy", "status": "failed"}]}
    assert len(attempts) == 1
    assert "private-password" not in capsys.readouterr().out + json.dumps(report)


@pytest.mark.parametrize("product", ["network", "protect", "access"])
def test_support_plugin_launcher_includes_skill_and_matching_pins(product):
    import support_smoke

    command, arguments, version = support_smoke.plugin_command(Path(__file__).resolve().parents[1], product, {})
    assert command == "uvx"
    assert arguments[-1] == f"unifi-{product}-mcp=={version}"


@pytest.mark.parametrize("defect", ["missing_skill", "version", "launcher"])
def test_support_plugin_rejects_broken_distribution(tmp_path, defect):
    import shutil

    import support_smoke

    source = Path(__file__).resolve().parents[1] / "plugins/unifi-network"
    target = tmp_path / "plugins/unifi-network"
    shutil.copytree(source, target)
    if defect == "missing_skill":
        (target / "skills/unifi-network-support/SKILL.md").unlink()
    elif defect == "version":
        path = target / ".codex-plugin/plugin.json"
        data = json.loads(path.read_text())
        data["version"] = "999.0.0"
        path.write_text(json.dumps(data))
    else:
        path = target / ".mcp.json"
        data = json.loads(path.read_text())
        data["mcpServers"]["unifi-network"]["command"] = "arbitrary-command"
        path.write_text(json.dumps(data))
    with pytest.raises((support_smoke.SupportSmokeError, FileNotFoundError)):
        support_smoke.plugin_command(tmp_path, "network", {})


@pytest.mark.parametrize("key", ["PATH", "PYTHONPATH", "UV_INDEX_URL", "UNIFI_TOOL_PERMISSION_MODE", "UNIFI_HOST"])
@pytest.mark.parametrize("manifest", [".mcp.json", ".claude-plugin/plugin.json", "both"])
def test_support_plugin_rejects_untrusted_environment_before_applying_it(tmp_path, key, manifest):
    import shutil

    import support_smoke

    target = tmp_path / "plugins/unifi-network"
    shutil.copytree(Path(__file__).resolve().parents[1] / "plugins/unifi-network", target)
    for filename in [".mcp.json", ".claude-plugin/plugin.json"] if manifest == "both" else [manifest]:
        path = target / filename
        data = json.loads(path.read_text())
        data["mcpServers"]["unifi-network"]["env"][key] = "${ATTACKER_CONTROLLED:-evil}"
        path.write_text(json.dumps(data))
    env = {"UNIFI_TOOL_PERMISSION_MODE": "confirm", "UNIFI_TOOL_REGISTRATION_MODE": "eager"}
    before = dict(env)
    with pytest.raises(support_smoke.SupportSmokeError, match="plugin_env_alignment"):
        support_smoke.plugin_command(tmp_path, "network", env)
    assert env == before


def test_support_cli_routes_without_generic_lifecycles(monkeypatch, tmp_path):
    import live_smoke
    import support_smoke

    monkeypatch.setattr(
        sys, "argv", ["live_smoke.py", "--server", "all", "--phase", "support", "--report-dir", str(tmp_path)]
    )
    run = AsyncMock(return_value={"success": True, "records": []})
    monkeypatch.setattr(support_smoke, "run_support_phase", run)
    assert live_smoke.main() == 0
    run.assert_awaited_once_with("all", live_smoke.REPO_ROOT, None)
    assert len(list(tmp_path.glob("support-*.json"))) == 1


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
                    "schedule_enabled": True,
                    "schedule_reversed": False,
                    "schedule": ["mon-fri|0100-0700"],
                    "schedule_with_duration": [
                        {
                            "duration_minutes": 90,
                            "name": "smoke window updated",
                            "start_days_of_week": ["tue", "thu"],
                            "start_hour": 2,
                            "start_minute": 15,
                        }
                    ],
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
        "unifi_update_wlan",
        "unifi_get_wlan_details",
        "unifi_delete_wlan",
    ]
    assert calls[0][1]["wlan_data"]["enabled"] is False
    assert calls[0][1]["wlan_data"]["schedule_reversed"] is True
    assert calls[3][1]["update_data"] == {
        "schedule": ["mon-fri|0100-0700"],
        "schedule_reversed": False,
        "schedule_with_duration": [
            {
                "duration_minutes": 90,
                "name": "smoke window updated",
                "start_days_of_week": ["tue", "thu"],
                "start_hour": 2,
                "start_minute": 15,
            }
        ],
    }
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
