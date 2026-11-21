"""With no console host the server serves setup mode instead of exiting (real stdio, no sockets)."""

from __future__ import annotations

from stdio_server import run_server

from unifi_mcp_shared.testing import assert_unconfigured_server_serves_setup_mode

PASSWORD = "SENTINEL-setup-mode-password"


def test_setup_mode_without_host(tmp_path):
    run = run_server(tmp_path, {"UNIFI_INNERSPACE_PASSWORD": PASSWORD}, calls=(("innerspace_setup_status", {}),))

    assert run.returncode == 0, run.stderr
    assert run.server_name == "unifi-innerspace-mcp"
    assert run.tool_names == {"innerspace_setup_status"}
    assert "UNIFI_INNERSPACE_HOST" in run.instructions
    assert run.calls[0]["structuredContent"]["data"]["configured"] is False
    assert run.network_attempts == ""
    assert PASSWORD not in run.stderr + run.instructions


def test_unconfigured_server_serves_the_shared_setup_guidance(tmp_path):
    assert_unconfigured_server_serves_setup_mode(
        tmp_path,
        module="unifi_innerspace_mcp",
        env_prefix="INNERSPACE",
        plugin_name="unifi-innerspace",
        tool_prefix="innerspace",
        settings_file=True,
    )
