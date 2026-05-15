"""Tests for the MCP metadata smoke script helpers."""

from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_script_path = Path(__file__).parent.parent / "scripts" / "smoke_mcp_metadata.py"
_spec = importlib.util.spec_from_file_location("smoke_mcp_metadata", _script_path)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

MetadataSmokeError = _mod.MetadataSmokeError
ServerSpec = _mod.ServerSpec
validate_icons = _mod.validate_icons
validate_server_metadata = _mod.validate_server_metadata
validate_tool_titles = _mod.validate_tool_titles
smoke_env = _mod.smoke_env
selected_server_names = _mod.selected_server_names

PNG_DATA_URI = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\npayload").decode()


def _icon(size: str = "48x48"):
    return SimpleNamespace(src=PNG_DATA_URI, mimeType="image/png", sizes=[size])


def test_validate_icons_accepts_three_png_data_uri_sizes() -> None:
    validate_icons([_icon("48x48"), _icon("96x96"), _icon("192x192")], label="test")


def test_validate_icons_rejects_non_png_data() -> None:
    icon = SimpleNamespace(
        src="data:image/png;base64," + base64.b64encode(b"not-png").decode(), mimeType="image/png", sizes=["48x48"]
    )

    with pytest.raises(MetadataSmokeError, match="not PNG data"):
        validate_icons([icon, _icon("96x96"), _icon("192x192")], label="test")


def test_validate_server_metadata_checks_name_website_and_icons() -> None:
    spec = ServerSpec(
        package="unifi-network-mcp",
        command="unifi-network-mcp",
        expected_name="unifi-network-mcp",
        index_tool="unifi_tool_index",
        expected_index_title="UniFi Network Tool Index",
    )
    server_info = SimpleNamespace(
        name="unifi-network-mcp",
        websiteUrl="https://github.com/sirkirby/unifi-mcp",
        version="1.2.3",
        icons=[_icon("48x48"), _icon("96x96"), _icon("192x192")],
    )

    validate_server_metadata(spec, server_info)


def test_validate_tool_titles_requires_expected_title() -> None:
    spec = ServerSpec(
        package="unifi-network-mcp",
        command="unifi-network-mcp",
        expected_name="unifi-network-mcp",
        index_tool="unifi_tool_index",
        expected_index_title="UniFi Network Tool Index",
    )
    tools = [
        SimpleNamespace(name="unifi_tool_index", title="Wrong Title"),
    ]

    with pytest.raises(MetadataSmokeError, match="expected title"):
        validate_tool_titles(spec, tools)


def test_smoke_env_defaults_to_offline_metadata_credentials(monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_HOST", "10.0.0.1")
    monkeypatch.setenv("UNIFI_NETWORK_HOST", "10.0.0.2")

    env = smoke_env(use_current_env=False)

    assert env["UNIFI_HOST"] == "127.0.0.1"
    assert env["UNIFI_NETWORK_HOST"] == "127.0.0.1"
    assert env["UNIFI_USERNAME"] == "metadata-smoke"


def test_smoke_env_can_preserve_current_controller_env(monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_HOST", "10.0.0.1")

    env = smoke_env(use_current_env=True)

    assert env["UNIFI_HOST"] == "10.0.0.1"


def test_selected_server_names_skips_access_for_default_offline_smoke() -> None:
    assert selected_server_names(server="all", use_current_env=False) == ["network", "protect"]


def test_selected_server_names_includes_access_with_current_env() -> None:
    assert selected_server_names(server="all", use_current_env=True) == ["network", "protect", "access"]


def test_selected_server_names_rejects_access_without_current_env() -> None:
    with pytest.raises(MetadataSmokeError, match="requires --use-current-env"):
        selected_server_names(server="access", use_current_env=False)
