"""The server as a real stdio process: setup mode, registration modes, no startup request."""

from __future__ import annotations

import json

import pytest
from stdio_server import run_server

PASSWORD = "synthetic-drive-password-0123456789"
CONFIGURED = {
    "UNIFI_DRIVE_HOST": "192.0.2.10",
    "UNIFI_DRIVE_USERNAME": "synthetic-user",
    "UNIFI_DRIVE_PASSWORD": PASSWORD,
}

DOMAIN_TOOLS = {
    "drive_get_system_info",
    "drive_list_storage_pools",
    "drive_list_disks",
    "drive_list_shared_drives",
    "drive_get_shared_drive",
    "drive_get_file_services",
    "drive_set_file_service",
    "drive_list_nfs_connections",
    "drive_add_nfs_connection",
    "drive_update_nfs_connection",
    "drive_remove_nfs_connection",
}
META_TOOLS = {"drive_tool_index", "drive_execute", "drive_batch", "drive_batch_status"}


def test_no_host_serves_setup_mode(tmp_path):
    run = run_server(tmp_path, {})

    assert run.returncode == 0, run.stderr
    assert run.server_name == "unifi-drive-mcp"
    assert run.tool_names == {"drive_setup_status"}
    assert "UNIFI_DRIVE_HOST" in run.instructions
    assert run.network_attempts == ""


@pytest.mark.parametrize(
    ("mode", "registered"),
    [
        ("eager", META_TOOLS | DOMAIN_TOOLS),
        ("meta_only", META_TOOLS),
    ],
)
def test_configured_server_registers_tools_without_contacting_the_nas(tmp_path, mode, registered):
    run = run_server(tmp_path, {**CONFIGURED, "UNIFI_TOOL_REGISTRATION_MODE": mode})

    assert run.returncode == 0, run.stderr
    assert run.tool_names == registered
    assert run.network_attempts == ""
    assert PASSWORD not in run.stderr + json.dumps(run.tools)


def test_lazy_mode_lists_the_loader(tmp_path):
    run = run_server(tmp_path, CONFIGURED)

    assert run.returncode == 0, run.stderr
    assert META_TOOLS | {"drive_load_tools"} <= run.tool_names
    assert run.network_attempts == ""


def test_eager_category_filter(tmp_path):
    run = run_server(
        tmp_path, {**CONFIGURED, "UNIFI_TOOL_REGISTRATION_MODE": "eager", "UNIFI_ENABLED_CATEGORIES": "storage"}
    )

    assert run.tool_names & DOMAIN_TOOLS == {"drive_list_storage_pools", "drive_list_disks"}


def test_a_tool_call_reports_an_unreachable_nas_without_its_address_or_password(tmp_path):
    run = run_server(
        tmp_path,
        {**CONFIGURED, "UNIFI_TOOL_REGISTRATION_MODE": "eager"},
        calls=(("drive_list_disks", {}),),
    )

    payload = run.calls[0]["structuredContent"]
    assert payload["success"] is False
    assert payload["error"].startswith("Failed to list disks: ")
    assert "192.0.2.10" not in payload["error"]
    assert PASSWORD not in json.dumps(run.calls) + run.stderr
    assert "Traceback" not in run.stderr


def test_policy_denies_a_write_before_any_request(tmp_path):
    run = run_server(
        tmp_path,
        {**CONFIGURED, "UNIFI_TOOL_REGISTRATION_MODE": "eager", "UNIFI_POLICY_DRIVE_NFS_CONNECTIONS_DELETE": "false"},
        calls=(("drive_remove_nfs_connection", {"client": "192.0.2.76", "confirm": True}),),
    )

    payload = run.calls[0]["structuredContent"]
    assert payload["success"] is False
    assert "disabled by policy for nfs_connection" in payload["error"]
    assert run.network_attempts == ""
