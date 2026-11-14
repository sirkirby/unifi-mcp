"""Runtime singletons: where the key comes from and what the manifest lists."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from unifi_sitemanager_mcp import runtime
from unifi_sitemanager_mcp.categories import LAZY_DIRECT_TOOLS, SITEMANAGER_CATEGORY_MAP, TOOL_MODULE_MAP

MANIFEST = json.loads((Path(runtime.__file__).parent / "tools_manifest.json").read_text(encoding="utf-8"))


@pytest.fixture
def fresh_key(monkeypatch):
    for name in ("UNIFI_API_KEY", "UNIFI_SITEMANAGER_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    return runtime.get_api_key.__wrapped__


def test_key_comes_only_from_its_own_variable(fresh_key, monkeypatch):
    monkeypatch.setenv("UNIFI_API_KEY", "console-local-key")
    assert fresh_key() is None

    monkeypatch.setenv("UNIFI_SITEMANAGER_API_KEY", "cloud-key")
    assert fresh_key() == "cloud-key"


def test_bundled_config_carries_no_credential_or_destination():
    text = (Path(runtime.__file__).parent / "config" / "config.yaml").read_text(encoding="utf-8")
    settings = [line for line in text.splitlines() if not line.lstrip().startswith("#")]

    assert not any("API_KEY" in line or "api_key" in line for line in settings)
    assert not any("://" in line or "base_url" in line for line in settings)
    assert dict(runtime.config.unifi) == {}


def test_test_session_runs_unconfigured():
    assert runtime.connection_manager.configured is False


@pytest.mark.parametrize(("configured", "expected"), [("12.5", 12.5), ("0", 30.0), ("soon", 30.0)])
def test_timeout_falls_back_to_the_default(monkeypatch, configured, expected):
    monkeypatch.setattr(runtime.config.sitemanager, "timeout_seconds", configured)

    assert runtime._timeout_seconds() == expected


def test_manifest_lists_only_tools_the_server_serves():
    names = {tool["name"] for tool in MANIFEST["tools"]}

    assert MANIFEST["count"] == len(names) == 14
    assert "sitemanager_get_support_bundle" not in names
    assert set(TOOL_MODULE_MAP) == set(LAZY_DIRECT_TOOLS) == {name for name in names if name in TOOL_MODULE_MAP}
    assert len(TOOL_MODULE_MAP) == 9


def test_every_domain_tool_is_read_only_key_authenticated_and_categorized():
    tools = [tool for tool in MANIFEST["tools"] if tool["name"] in TOOL_MODULE_MAP]

    assert len(tools) == 9
    for tool in tools:
        assert tool["annotations"] == {"readOnlyHint": True, "openWorldHint": False}, tool["name"]
        assert tool["auth_method"] == "api_key_only", tool["name"]
        assert tool["permission_action"] == "read", tool["name"]
        assert tool["permission_category"] in SITEMANAGER_CATEGORY_MAP, tool["name"]
        assert not any(character.isdigit() for character in tool["name"]), tool["name"]


def test_titles_spell_acronyms():
    titles = {tool["name"]: tool["title"] for tool in MANIFEST["tools"]}

    assert titles["sitemanager_get_isp_metrics"] == "Get ISP Metrics"
    assert titles["sitemanager_list_sdwan_configs"] == "List SD-WAN Configs"
