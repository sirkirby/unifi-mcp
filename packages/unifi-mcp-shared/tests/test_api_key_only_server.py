"""Shared support for a server whose only credential is its own API key."""

import logging
from unittest.mock import AsyncMock

import pytest
from mcp.server.mcpserver import MCPServer as FastMCP
from omegaconf import OmegaConf
from unifi_mcp_shared.bootstrap import resolve_env
from unifi_mcp_shared.metadata import mcp_icons_for_server, tool_title_from_name
from unifi_mcp_shared.settings_file import SettingsFileReport
from unifi_mcp_shared.setup_required import api_key_setup_required_message, serve_setup_required

LOGGER = logging.getLogger("test")
_VARS = [
    f"UNIFI_{level}API_KEY{suffix}"
    for level in ("", "SITEMANAGER_", "NETWORK_")
    for suffix in ("", "_FILE", "_COMMAND")
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in _VARS:
        monkeypatch.delenv(var, raising=False)


def _isolated() -> str | None:
    return resolve_env("api_key", env_prefix="SITEMANAGER", logger=LOGGER, shared_fallback=False)


def test_isolated_key_ignores_the_shared_level(monkeypatch, tmp_path):
    shared_file = tmp_path / "shared-key"
    shared_file.write_text("console-local-key-from-file")
    monkeypatch.setenv("UNIFI_API_KEY", "console-local-key")
    assert _isolated() is None

    monkeypatch.delenv("UNIFI_API_KEY")
    monkeypatch.setenv("UNIFI_API_KEY_FILE", str(shared_file))
    assert _isolated() is None


def test_isolated_key_reads_its_own_level(monkeypatch, tmp_path):
    monkeypatch.setenv("UNIFI_API_KEY", "console-local-key")
    monkeypatch.setenv("UNIFI_SITEMANAGER_API_KEY", "cloud-key")
    assert _isolated() == "cloud-key"

    own_file = tmp_path / "own-key"
    own_file.write_text("cloud-key-from-file\n")
    monkeypatch.delenv("UNIFI_SITEMANAGER_API_KEY")
    monkeypatch.setenv("UNIFI_SITEMANAGER_API_KEY_FILE", str(own_file))
    assert _isolated() == "cloud-key-from-file"


def test_shared_fallback_is_unchanged_by_default(monkeypatch):
    monkeypatch.setenv("UNIFI_API_KEY", "console-local-key")
    assert resolve_env("api_key", env_prefix="NETWORK", logger=LOGGER) == "console-local-key"


def _message(state: str | None) -> str:
    report = None if state is None else SettingsFileReport(state=state, path="/home/someone/.config/x.env")
    return api_key_setup_required_message(
        plugin_name="unifi-sitemanager",
        env_prefix="SITEMANAGER",
        key_source="unifi.ui.com > Settings > API Keys.",
        report=report,
    )


def test_api_key_guidance_names_the_key_and_no_controller_login():
    text = _message(None)
    assert "no API key is set" in text
    assert "unifi.ui.com > Settings > API Keys." in text
    assert "/unifi-sitemanager:unifi-sitemanager-setup" in text
    assert "~/.config/unifi-mcp/sitemanager.env" in text
    assert "UNIFI_SITEMANAGER_API_KEY" in text and "UNIFI_SETTINGS_FILE" in text
    assert "does not use UNIFI_API_KEY" in text
    assert "_HOST" not in text and "USERNAME" not in text and "PASSWORD" not in text
    assert "Standalone: restart the server" in text
    assert len(_message("missing").splitlines()) <= 20


@pytest.mark.parametrize(("state", "phrase"), [("missing", "does not exist yet"), ("ignored", "was ignored")])
def test_api_key_guidance_names_settings_file_state_without_its_path(state, phrase):
    text = _message(state)
    assert phrase in text
    assert "/home/someone" not in text


async def test_setup_mode_serves_a_supplied_message(monkeypatch):
    monkeypatch.setattr("unifi_mcp_shared.transport.run_transports", AsyncMock())
    monkeypatch.setattr(
        "unifi_mcp_shared.transport.resolve_http_config", lambda *a, **kw: (False, "streamable-http", "127.0.0.1", 3003)
    )
    server = FastMCP("test")

    await serve_setup_required(
        server=server,
        config=OmegaConf.create({"unifi": {}, "server": {"http": {}}}),
        plugin_name="unifi-sitemanager",
        env_prefix="SITEMANAGER",
        tool_prefix="sitemanager",
        default_port=3003,
        logger=LOGGER,
        message="custom guidance",
    )

    assert server._lowlevel_server.instructions == "custom guidance"


def test_site_manager_icons_and_titles():
    icons = mcp_icons_for_server("sitemanager")
    assert [icon.sizes for icon in icons] == [["48x48"], ["96x96"], ["192x192"]]
    assert tool_title_from_name("sitemanager_get_isp_metrics") == "Get ISP Metrics"
    assert tool_title_from_name("sitemanager_list_sdwan_configs") == "List SD-WAN Configs"
