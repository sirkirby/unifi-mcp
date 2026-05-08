"""Unit tests for StrictKwargFastMCP transport-layer kwarg validation."""

from __future__ import annotations

import json
import pathlib
from unittest.mock import AsyncMock, patch

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from unifi_mcp_shared.strict_dispatch import StrictKwargFastMCP, _load_allowed_kwargs


def _write_manifest(tmp_path: pathlib.Path, tools: list[dict]) -> pathlib.Path:
    """Write a tools_manifest.json with the given tool entries and return its path."""
    path = tmp_path / "tools_manifest.json"
    path.write_text(json.dumps({"count": len(tools), "tools": tools}), encoding="utf-8")
    return path


def _make_tool(name: str, properties: dict[str, dict] | None) -> dict:
    """Build a manifest tool entry. Pass ``properties=None`` to omit the input schema."""
    if properties is None:
        return {"name": name, "schema": {}}
    return {
        "name": name,
        "schema": {
            "input": {
                "type": "object",
                "properties": properties,
                "required": [],
            }
        },
    }


@pytest.fixture
def acl_manifest(tmp_path: pathlib.Path) -> pathlib.Path:
    """A manifest with a single create_acl_rule-shaped tool."""
    tools = [
        _make_tool(
            "unifi_create_acl_rule",
            {
                "acl_index": {"type": "integer"},
                "action": {"type": "string"},
                "confirm": {"type": "boolean"},
                "destination_macs": {"type": "array"},
                "enabled": {"type": "boolean"},
                "name": {"type": "string"},
                "network_id": {"type": "string"},
                "source_macs": {"type": "array"},
            },
        ),
        _make_tool("unifi_list_devices", {"site": {"type": "string"}}),
        _make_tool("unifi_no_args_tool", {}),
        _make_tool(
            "unifi_update_policy",
            {"policy_id": {"type": "string"}, "policy_data": {"type": "object"}},
        ),
    ]
    return _write_manifest(tmp_path, tools)


# -----------------------------
# call_tool dispatch behavior
# -----------------------------


async def test_unknown_kwarg_rejected(acl_manifest: pathlib.Path) -> None:
    server = StrictKwargFastMCP("test", tools_manifest_path=acl_manifest)
    with pytest.raises(ToolError) as excinfo:
        await server.call_tool(
            "unifi_create_acl_rule",
            {"name": "x", "action": "REJECT", "source_mac": "aa:bb:cc:dd:ee:ff"},
        )
    msg = str(excinfo.value)
    assert msg == (
        "Invalid params for 'unifi_create_acl_rule': "
        "unknown arguments {source_mac}. "
        "Valid arguments: ["
        "acl_index, action, confirm, destination_macs, enabled, name, network_id, source_macs"
        "]."
    )


async def test_known_kwargs_pass_through(acl_manifest: pathlib.Path) -> None:
    server = StrictKwargFastMCP("test", tools_manifest_path=acl_manifest)
    sentinel = [{"type": "text", "text": "ok"}]
    with patch.object(FastMCP, "call_tool", new=AsyncMock(return_value=sentinel)) as super_mock:
        result = await server.call_tool(
            "unifi_create_acl_rule",
            {"name": "rule", "action": "REJECT", "enabled": True},
        )
    assert result is sentinel
    super_mock.assert_awaited_once_with(
        "unifi_create_acl_rule",
        {"name": "rule", "action": "REJECT", "enabled": True},
    )


async def test_empty_kwargs_pass_through(acl_manifest: pathlib.Path) -> None:
    server = StrictKwargFastMCP("test", tools_manifest_path=acl_manifest)
    sentinel = [{"type": "text", "text": "ok"}]
    with patch.object(FastMCP, "call_tool", new=AsyncMock(return_value=sentinel)) as super_mock:
        result = await server.call_tool("unifi_list_devices", {})
    assert result is sentinel
    super_mock.assert_awaited_once_with("unifi_list_devices", {})


async def test_no_args_tool_pass_through(acl_manifest: pathlib.Path) -> None:
    """Zero-arg tools accept empty kwargs without error."""
    server = StrictKwargFastMCP("test", tools_manifest_path=acl_manifest)
    sentinel = [{"type": "text", "text": "ok"}]
    with patch.object(FastMCP, "call_tool", new=AsyncMock(return_value=sentinel)) as super_mock:
        result = await server.call_tool("unifi_no_args_tool", {})
    assert result is sentinel
    super_mock.assert_awaited_once_with("unifi_no_args_tool", {})


async def test_no_args_tool_rejects_unknown_kwargs(acl_manifest: pathlib.Path) -> None:
    """A zero-arg tool given any kwarg should still reject — empty allowed set."""
    server = StrictKwargFastMCP("test", tools_manifest_path=acl_manifest)
    with pytest.raises(ToolError) as excinfo:
        await server.call_tool("unifi_no_args_tool", {"bogus": 1})
    assert "unknown arguments {bogus}" in str(excinfo.value)
    assert "Valid arguments: []" in str(excinfo.value)


async def test_dict_param_doesnt_recurse(acl_manifest: pathlib.Path) -> None:
    """Inner dict keys are NOT inspected — only top-level kwargs."""
    server = StrictKwargFastMCP("test", tools_manifest_path=acl_manifest)
    sentinel = [{"type": "text", "text": "ok"}]
    args = {"policy_id": "p1", "policy_data": {"foo": "bar", "nested_unknown": 42}}
    with patch.object(FastMCP, "call_tool", new=AsyncMock(return_value=sentinel)) as super_mock:
        result = await server.call_tool("unifi_update_policy", args)
    assert result is sentinel
    super_mock.assert_awaited_once_with("unifi_update_policy", args)


async def test_unknown_tool_delegates_to_super(acl_manifest: pathlib.Path) -> None:
    """Tools not in the manifest pass through so FastMCP's own 'Unknown tool' path runs."""
    server = StrictKwargFastMCP("test", tools_manifest_path=acl_manifest)
    sentinel = [{"type": "text", "text": "delegated"}]
    with patch.object(FastMCP, "call_tool", new=AsyncMock(return_value=sentinel)) as super_mock:
        result = await server.call_tool("unifi_not_in_manifest", {"anything": 1})
    assert result is sentinel
    super_mock.assert_awaited_once_with("unifi_not_in_manifest", {"anything": 1})


async def test_missing_required_not_double_reported(acl_manifest: pathlib.Path) -> None:
    """Missing required args are FastMCP's job — wrapper must not raise on them."""
    server = StrictKwargFastMCP("test", tools_manifest_path=acl_manifest)
    sentinel = [{"type": "text", "text": "delegated"}]
    # Only pass a known kwarg; another required one is missing — wrapper should still delegate.
    with patch.object(FastMCP, "call_tool", new=AsyncMock(return_value=sentinel)) as super_mock:
        result = await server.call_tool("unifi_create_acl_rule", {"name": "rule"})
    assert result is sentinel
    super_mock.assert_awaited_once_with("unifi_create_acl_rule", {"name": "rule"})


# -----------------------------
# Constructor robustness
# -----------------------------


def test_constructor_handles_missing_manifest_gracefully(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    missing = tmp_path / "does_not_exist.json"
    with caplog.at_level("WARNING"):
        server = StrictKwargFastMCP("test", tools_manifest_path=missing)
    assert server._allowed_kwargs == {}
    assert any("not found" in record.message for record in caplog.records)


def test_constructor_handles_malformed_manifest_gracefully(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{ this is not valid json", encoding="utf-8")
    with caplog.at_level("WARNING"):
        server = StrictKwargFastMCP("test", tools_manifest_path=bad)
    assert server._allowed_kwargs == {}
    assert any("not valid JSON" in record.message for record in caplog.records)


def test_constructor_handles_missing_tools_key(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    weird = tmp_path / "weird.json"
    weird.write_text(json.dumps({"count": 0}), encoding="utf-8")
    with caplog.at_level("WARNING"):
        server = StrictKwargFastMCP("test", tools_manifest_path=weird)
    assert server._allowed_kwargs == {}
    assert any("missing 'tools' list" in record.message for record in caplog.records)


def test_constructor_with_no_manifest_path() -> None:
    """Omitting tools_manifest_path yields empty cache — every call falls through."""
    server = StrictKwargFastMCP("test")
    assert server._allowed_kwargs == {}


# -----------------------------
# Manifest loader edge cases
# -----------------------------


def test_loader_treats_tools_without_input_schema_as_zero_arg(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = _write_manifest(
        tmp_path,
        [_make_tool("unifi_partial", None), _make_tool("unifi_normal", {"x": {"type": "string"}})],
    )
    with caplog.at_level("WARNING"):
        allowed = _load_allowed_kwargs(path)
    assert allowed["unifi_partial"] == frozenset()
    assert allowed["unifi_normal"] == frozenset({"x"})
    assert any("had no input schema" in record.message for record in caplog.records)
