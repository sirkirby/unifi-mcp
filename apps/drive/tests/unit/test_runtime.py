"""Runtime singletons, manifest contents and categories."""

from __future__ import annotations

import json
from pathlib import Path

from unifi_drive_mcp import runtime
from unifi_drive_mcp.bootstrap import load_config
from unifi_drive_mcp.categories import DRIVE_CATEGORY_MAP, TOOL_MODULE_MAP

MANIFEST = json.loads((Path(runtime.__file__).parent / "tools_manifest.json").read_text(encoding="utf-8"))

READ_TOOLS = {
    "drive_get_system_info",
    "drive_list_storage_pools",
    "drive_list_disks",
    "drive_list_shared_drives",
    "drive_get_shared_drive",
    "drive_get_file_services",
    "drive_list_nfs_connections",
    "drive_list_logs",
    "drive_get_storage_usage",
    "drive_get_smb_advanced_settings",
    "drive_get_rsync_settings",
    "drive_get_network_throughput",
    "drive_get_fan_profile",
    "drive_get_disk_stats",
    "drive_get_snapshot_overview",
    "drive_list_snapshots",
}
WRITE_TOOLS = {
    "drive_set_file_service",
    "drive_add_nfs_connection",
    "drive_update_nfs_connection",
    "drive_remove_nfs_connection",
}


def test_test_session_runs_unconfigured():
    assert runtime.connection_manager.configured is False


def test_bundled_config_carries_no_credential_or_host():
    assert runtime.config.unifi.host == ""
    assert runtime.config.unifi.username == ""
    assert runtime.config.unifi.password == ""


def test_gateway_credentials_and_pin_are_not_used_for_the_nas(monkeypatch):
    monkeypatch.delenv("CONFIG_PATH", raising=False)
    monkeypatch.setenv("UNIFI_HOST", "192.0.2.1")
    monkeypatch.setenv("UNIFI_USERNAME", "gateway-admin")
    monkeypatch.setenv("UNIFI_PASSWORD", "gateway-password")
    monkeypatch.setenv("UNIFI_PORT", "8443")
    monkeypatch.setenv("UNIFI_SSL_FINGERPRINT", "AA" * 32)

    cfg = load_config()

    assert (cfg.unifi.host, cfg.unifi.username, cfg.unifi.password) == ("", "", "")
    assert int(cfg.unifi.port) == 443
    assert runtime._ssl_fingerprint(cfg.unifi) is None


def test_drive_level_credentials_and_pin_are_used(monkeypatch):
    monkeypatch.delenv("CONFIG_PATH", raising=False)
    monkeypatch.setenv("UNIFI_DRIVE_HOST", "192.0.2.10")
    monkeypatch.setenv("UNIFI_DRIVE_USERNAME", "nas-user")
    monkeypatch.setenv("UNIFI_DRIVE_PASSWORD", "nas-password")
    monkeypatch.setenv("UNIFI_DRIVE_SSL_FINGERPRINT", "BB" * 32)

    cfg = load_config()

    assert (cfg.unifi.host, cfg.unifi.username, cfg.unifi.password) == ("192.0.2.10", "nas-user", "nas-password")
    assert runtime._ssl_fingerprint(cfg.unifi) == "BB" * 32


def test_manifest_lists_exactly_the_drive_tools():
    assert set(TOOL_MODULE_MAP) == READ_TOOLS | WRITE_TOOLS
    assert "drive_get_support_bundle" not in {tool["name"] for tool in MANIFEST["tools"]}


def test_read_tools_are_read_only_and_categorized():
    tools = {tool["name"]: tool for tool in MANIFEST["tools"]}
    for name in READ_TOOLS:
        assert tools[name]["annotations"] == {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False}
        assert tools[name]["permission_action"] == "read"
        assert tools[name]["permission_category"] in DRIVE_CATEGORY_MAP


def test_write_tools_preview_first_and_only_removal_is_destructive():
    tools = {tool["name"]: tool for tool in MANIFEST["tools"]}
    for name in WRITE_TOOLS:
        tool = tools[name]
        assert tool["annotations"]["readOnlyHint"] is False, name
        assert "confirm" in tool["schema"]["input"]["properties"], name
        assert tool["permission_category"] in DRIVE_CATEGORY_MAP, name
        expected = name == "drive_remove_nfs_connection"
        assert tool["annotations"]["destructiveHint"] is expected, name


def test_no_tool_erases_or_deletes_storage():
    names = {tool["name"] for tool in MANIFEST["tools"]}
    assert not any(word in name for name in names for word in ("erase", "delete", "format", "wipe"))


def test_titles_spell_acronyms():
    titles = {tool["name"]: tool["title"] for tool in MANIFEST["tools"]}
    assert titles["drive_list_nfs_connections"] == "List NFS Connections"
