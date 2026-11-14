"""The server as a real stdio process: setup mode, key isolation, registration modes."""

from __future__ import annotations

import json

import pytest
from stdio_server import run_server

KEY = "synthetic-site-manager-key-0123456789"
CONSOLE_KEY = "synthetic-console-local-key-9876543210"

DOMAIN_TOOLS = {
    "sitemanager_list_hosts",
    "sitemanager_get_host",
    "sitemanager_list_sites",
    "sitemanager_list_devices",
    "sitemanager_get_isp_metrics",
    "sitemanager_query_isp_metrics",
    "sitemanager_list_sdwan_configs",
    "sitemanager_get_sdwan_config",
    "sitemanager_get_sdwan_config_status",
}
META_TOOLS = {
    "sitemanager_tool_index",
    "sitemanager_execute",
    "sitemanager_batch",
    "sitemanager_batch_status",
}
SETUP_TOOLS = {"sitemanager_setup_status"}


def _assert_setup_mode(run) -> None:
    assert run.returncode == 0, run.stderr
    assert run.tool_names == SETUP_TOOLS
    assert "no API key is set" in run.instructions
    assert "UNIFI_SITEMANAGER_API_KEY" in run.instructions
    assert "does not use UNIFI_API_KEY" in run.instructions
    assert run.network_attempts == ""


def test_no_key_serves_setup_mode(tmp_path):
    run = run_server(tmp_path, {}, calls=(("sitemanager_setup_status", {}),))

    _assert_setup_mode(run)
    assert run.server_name == "unifi-sitemanager-mcp"
    assert run.tools[0]["annotations"]["readOnlyHint"] is True
    data = run.calls[0]["structuredContent"]["data"]
    assert data["configured"] is False and data["message"] == run.instructions


def test_console_key_and_config_file_key_are_never_used(tmp_path):
    """Neither UNIFI_API_KEY nor a CONFIG_PATH file can supply the key."""
    config = tmp_path / "config.yaml"
    config.write_text(
        "unifi:\n"
        f"  api_key: {CONSOLE_KEY}\n"
        "server:\n"
        "  http: {}\n"
        "  diagnostics: {}\n"
        "sitemanager:\n"
        f"  api_key: {CONSOLE_KEY}\n",
        encoding="utf-8",
    )

    run = run_server(
        tmp_path,
        {"UNIFI_API_KEY": CONSOLE_KEY, "UNIFI_NETWORK_API_KEY": CONSOLE_KEY, "CONFIG_PATH": str(config)},
    )

    _assert_setup_mode(run)
    assert CONSOLE_KEY not in run.stderr + run.instructions + json.dumps(run.tools)


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("lazy", META_TOOLS | {"sitemanager_load_tools"} | DOMAIN_TOOLS),
        ("eager", META_TOOLS | DOMAIN_TOOLS),
        ("meta_only", META_TOOLS),
    ],
)
def test_configured_server_registers_tools_without_network_access(tmp_path, mode, expected):
    run = run_server(tmp_path, {"UNIFI_SITEMANAGER_API_KEY": KEY, "UNIFI_TOOL_REGISTRATION_MODE": mode})

    assert run.returncode == 0, run.stderr
    assert run.tool_names == expected
    assert run.network_attempts == ""
    assert KEY not in run.stderr + json.dumps(run.tools)
    listed = {tool["name"]: tool for tool in run.tools}
    for name in sorted(DOMAIN_TOOLS & expected):
        annotations = listed[name]["annotations"]
        assert annotations["readOnlyHint"] is True and annotations["openWorldHint"] is False, name


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("sites", {"sitemanager_list_sites"}),
        ("devices", {"sitemanager_list_devices"}),
        ("hosts", {"sitemanager_list_hosts", "sitemanager_get_host"}),
    ],
)
def test_eager_category_filter_registers_only_that_category(tmp_path, category, expected):
    run = run_server(
        tmp_path,
        {
            "UNIFI_SITEMANAGER_API_KEY": KEY,
            "UNIFI_TOOL_REGISTRATION_MODE": "eager",
            "UNIFI_ENABLED_CATEGORIES": category,
        },
    )

    assert run.returncode == 0, run.stderr
    assert run.tool_names & DOMAIN_TOOLS == expected


def test_read_only_client_reaches_every_tool_in_the_default_mode(tmp_path):
    """sitemanager_execute is not read-only, so lazy mode lists the tools directly."""
    run = run_server(tmp_path, {"UNIFI_SITEMANAGER_API_KEY": KEY})

    read_only = {tool["name"] for tool in run.tools if (tool.get("annotations") or {}).get("readOnlyHint")}
    assert DOMAIN_TOOLS <= read_only
    assert "sitemanager_execute" not in read_only


def test_a_tool_call_reports_an_unreachable_api_without_the_key(tmp_path):
    run = run_server(tmp_path, {"UNIFI_SITEMANAGER_API_KEY": KEY}, calls=(("sitemanager_list_hosts", {}),))

    payload = run.calls[0]["structuredContent"]
    assert payload["success"] is False
    assert payload["error"].startswith("Failed to list hosts: ")
    assert KEY not in json.dumps(run.calls) + run.stderr
    assert "Traceback" not in run.stderr
