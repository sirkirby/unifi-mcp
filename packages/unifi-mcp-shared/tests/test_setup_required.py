"""Setup-mode guidance for a server with no controller host."""

import pytest
from omegaconf import OmegaConf
from unifi_mcp_shared.settings_file import SettingsFileReport
from unifi_mcp_shared.setup_required import controller_host_configured, setup_required_message


@pytest.mark.parametrize(
    ("cfg_dict", "configured"),
    [
        ({"unifi": {"host": "192.0.2.10"}}, True),
        ({"unifi": {"host": ""}}, False),
        ({"unifi": {"host": "  "}}, False),
        ({"unifi": {}}, False),
        ({}, False),
    ],
)
def test_controller_host_configured(cfg_dict, configured):
    assert controller_host_configured(OmegaConf.create(cfg_dict)) is configured


def message(state: str | None) -> str:
    report = None if state is None else SettingsFileReport(state=state, path="/home/someone/.config/x.env")
    return setup_required_message(plugin_name="unifi-protect", env_prefix="PROTECT", report=report)


def test_names_every_setup_path():
    text = message(None)
    assert "not configured" in text
    assert "/unifi-protect:unifi-protect-setup" in text
    assert ".claude/settings.local.json" in text
    assert "Codex or OpenClaw: run the unifi-protect-setup skill" in text
    assert "~/.config/unifi-mcp/protect.env" in text
    assert "UNIFI_PROTECT_HOST" in text and "UNIFI_SETTINGS_FILE" in text
    assert "does not exist yet" not in text and "ignored" not in text
    assert "Claude Code: run /reload-plugins or start a new session" in text
    assert "/mcp reconnect does not load new plugin options" in text
    assert "Codex: restart Codex or start a new session" in text
    assert "OpenClaw: start a new session or run openclaw gateway restart" in text
    assert "Standalone: restart the server" in text
    assert "reconnect it in the client" not in text
    assert "Any other UniFi plugins you have installed (Network, Protect, Access) need the same setup" in text


def test_message_stays_short():
    assert len(message("missing").splitlines()) <= 20


@pytest.mark.parametrize(("state", "phrase"), [("missing", "does not exist yet"), ("ignored", "was ignored")])
def test_settings_file_state_is_named_without_its_path(state, phrase):
    text = message(state)
    assert phrase in text
    assert "/home/someone" not in text


def test_loaded_file_without_host_adds_no_file_hint():
    text = message("loaded")
    assert "does not exist yet" not in text and "was ignored" not in text


@pytest.mark.asyncio
@pytest.mark.parametrize(("http_enabled", "expected"), [(True, "y" * 40), (False, None)])
async def test_setup_mode_keeps_config_auth_token(monkeypatch, http_enabled, expected):
    """A token set only in config.yaml still guards the setup-mode HTTP endpoint."""
    import logging
    from unittest.mock import AsyncMock

    from mcp.server.mcpserver import MCPServer as FastMCP
    from unifi_mcp_shared.setup_required import serve_setup_required

    for name in ("UNIFI_PROTECT_MCP_HTTP_AUTH_TOKEN", "UNIFI_MCP_HTTP_AUTH_TOKEN"):
        for suffix in ("", "_FILE", "_COMMAND"):
            monkeypatch.delenv(f"{name}{suffix}", raising=False)
    transport = AsyncMock()
    monkeypatch.setattr("unifi_mcp_shared.transport.run_transports", transport)
    monkeypatch.setattr(
        "unifi_mcp_shared.transport.resolve_http_config",
        lambda *a, **kw: (http_enabled, "streamable-http", "127.0.0.1", 3001),
    )
    config = OmegaConf.create({"unifi": {}, "server": {"http": {"enabled": http_enabled, "auth_token": "y" * 40}}})
    await serve_setup_required(
        server=FastMCP("test"),
        config=config,
        plugin_name="unifi-protect",
        env_prefix="PROTECT",
        tool_prefix="protect",
        default_port=3001,
        logger=logging.getLogger("test"),
    )
    assert transport.await_args.kwargs["auth_token"] == expected
    # Selects the UNIFI_PROTECT_ spelling of the trusted networks, like the token's.
    assert transport.await_args.kwargs["env_prefix"] == "PROTECT"
