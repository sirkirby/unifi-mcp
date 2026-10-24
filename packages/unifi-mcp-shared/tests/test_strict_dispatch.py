"""Unit tests for StrictKwargFastMCP transport-layer kwarg validation."""

from __future__ import annotations

import json
import pathlib
from unittest.mock import AsyncMock, patch

import pytest
from mcp.server.mcpserver import MCPServer as FastMCP
from mcp.server.mcpserver.exceptions import ToolError
from unifi_core.redaction import REDACTED
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


@pytest.mark.parametrize(
    ("tool_name", "args"),
    [
        ("unifi_create_acl_rule", {"name": "rule", "action": "REJECT", "enabled": True}),
        ("unifi_list_devices", {}),
        ("unifi_no_args_tool", {}),
        ("unifi_update_policy", {"policy_id": "p1", "policy_data": {"foo": "bar", "nested_unknown": 42}}),
        ("unifi_not_in_manifest", {"anything": 1}),
        ("unifi_create_acl_rule", {"name": "rule"}),
    ],
)
async def test_valid_or_delegated_calls_pass_through(acl_manifest: pathlib.Path, tool_name: str, args: dict) -> None:
    server = StrictKwargFastMCP("test", tools_manifest_path=acl_manifest)
    sentinel = [{"type": "text", "text": "ok"}]
    with patch.object(FastMCP, "call_tool", new=AsyncMock(return_value=sentinel)) as super_mock:
        result = await server.call_tool(tool_name, args)
    assert result is sentinel
    super_mock.assert_awaited_once_with(tool_name, args, context=None)


async def test_no_args_tool_rejects_unknown_kwargs(acl_manifest: pathlib.Path) -> None:
    """A zero-arg tool given any kwarg should still reject — empty allowed set."""
    server = StrictKwargFastMCP("test", tools_manifest_path=acl_manifest)
    with pytest.raises(ToolError) as excinfo:
        await server.call_tool("unifi_no_args_tool", {"bogus": 1})
    assert "unknown arguments {bogus}" in str(excinfo.value)
    assert "Valid arguments: []" in str(excinfo.value)


# -----------------------------
# redaction-marker write-back guard
# -----------------------------


async def test_rejects_top_level_redaction_marker(tmp_path: pathlib.Path) -> None:
    """A sensitive top-level kwarg echoed back as the marker is rejected."""
    manifest = _write_manifest(
        tmp_path,
        [_make_tool("unifi_update_snmp_settings", {"enabled": {"type": "boolean"}, "community": {"type": "string"}})],
    )
    server = StrictKwargFastMCP("test", tools_manifest_path=manifest)
    with pytest.raises(ToolError) as excinfo:
        await server.call_tool("unifi_update_snmp_settings", {"enabled": True, "community": REDACTED})
    msg = str(excinfo.value)
    assert "community" in msg
    assert "redaction marker" in msg


async def test_rejects_nested_redaction_marker(acl_manifest: pathlib.Path) -> None:
    """Unlike the kwarg check, the marker guard recurses into inner dicts."""
    server = StrictKwargFastMCP("test", tools_manifest_path=acl_manifest)
    with pytest.raises(ToolError) as excinfo:
        await server.call_tool(
            "unifi_update_policy",
            {"policy_id": "p1", "policy_data": {"x_passphrase": REDACTED}},
        )
    assert "policy_data.x_passphrase" in str(excinfo.value)


async def test_marker_guard_allows_non_sensitive_field_equal_to_marker(acl_manifest: pathlib.Path) -> None:
    """A non-sensitive field whose value equals the marker passes — the guard
    only fires on keys the shared vocabulary deems sensitive."""
    server = StrictKwargFastMCP("test", tools_manifest_path=acl_manifest)
    sentinel = [{"type": "text", "text": "ok"}]
    args = {"name": REDACTED, "action": "REJECT"}
    with patch.object(FastMCP, "call_tool", new=AsyncMock(return_value=sentinel)) as super_mock:
        result = await server.call_tool("unifi_create_acl_rule", args)
    assert result is sentinel
    super_mock.assert_awaited_once_with("unifi_create_acl_rule", args, context=None)


async def test_marker_guard_runs_for_unknown_tools(tmp_path: pathlib.Path) -> None:
    """The guard is not gated on manifest presence: a tool absent from the
    manifest still cannot smuggle a marker write-back through."""
    manifest = _write_manifest(tmp_path, [_make_tool("unifi_known", {"x": {"type": "string"}})])
    server = StrictKwargFastMCP("test", tools_manifest_path=manifest)
    with pytest.raises(ToolError):
        await server.call_tool("unifi_not_in_manifest", {"token": REDACTED})


# -----------------------------
# Constructor robustness
# -----------------------------


@pytest.mark.parametrize(
    ("kind", "expected_warning"),
    [
        ("missing", "not found"),
        ("malformed", "not valid JSON"),
        ("missing_tools", "missing 'tools' list"),
        ("none", None),
    ],
)
def test_constructor_handles_unavailable_or_invalid_manifest_gracefully(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture, kind: str, expected_warning: str | None
) -> None:
    if kind == "none":
        server = StrictKwargFastMCP("test")
        assert server._allowed_kwargs == {}
        return
    path = tmp_path / f"{kind}.json"
    if kind == "malformed":
        path.write_text("{ this is not valid json", encoding="utf-8")
    elif kind == "missing_tools":
        path.write_text(json.dumps({"count": 0}), encoding="utf-8")
    with caplog.at_level("WARNING"):
        server = StrictKwargFastMCP("test", tools_manifest_path=path)
    assert server._allowed_kwargs == {}
    assert any(expected_warning in record.message for record in caplog.records)


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


# -----------------------------
# MAC parameter guidance
# -----------------------------


@pytest.fixture
def mac_manifest(tmp_path: pathlib.Path) -> pathlib.Path:
    """Network tools use mac_address for the subject MAC."""
    tools = [
        _make_tool("unifi_get_client_details", {"mac_address": {"type": "string"}}),
        _make_tool("unifi_get_client_sessions", {"mac_address": {"type": "string"}, "limit": {"type": "integer"}}),
        _make_tool("unifi_get_switch_ports", {"mac_address": {"type": "string"}}),
        _make_tool("unifi_recent_events", {"mac_address": {"type": "string"}}),
        _make_tool("unifi_list_networks", {"site": {"type": "string"}}),
        _make_tool("unifi_trigger_rf_scan", {"ap_mac": {"type": "string"}}),
        _make_tool("unifi_two_macs", {"client_mac": {"type": "string"}, "device_mac": {"type": "string"}}),
    ]
    return _write_manifest(tmp_path, tools)


@pytest.mark.parametrize(
    ("tool", "rejected", "canonical"),
    [
        ("unifi_get_client_details", "client_mac", "mac_address"),
        ("unifi_get_client_details", "device_mac", "mac_address"),
        ("unifi_get_client_details", "mac", "mac_address"),
        ("unifi_get_client_sessions", "client_mac", "mac_address"),
        ("unifi_get_switch_ports", "device_mac", "mac_address"),
        ("unifi_recent_events", "mac", "mac_address"),
    ],
)
async def test_mac_spelling_error_names_the_canonical_parameter(
    mac_manifest: pathlib.Path, tool: str, rejected: str, canonical: str
) -> None:
    """The MAC parameter is spelled differently across tools; the rejection says which one this tool takes."""
    server = StrictKwargFastMCP("test", tools_manifest_path=mac_manifest)
    with pytest.raises(ToolError) as excinfo:
        await server.call_tool(tool, {rejected: "aa:bb:cc:dd:ee:ff"})
    msg = str(excinfo.value)
    assert f"unknown arguments {{{rejected}}}" in msg
    assert f"'{tool}' takes the MAC address as '{canonical}'." in msg


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("unifi_get_client_details", {"hostname": "x"}),
        ("unifi_two_macs", {"mac_address": "aa:bb:cc:dd:ee:ff"}),
        ("unifi_trigger_rf_scan", {"client_mac": "aa:bb:cc:dd:ee:ff"}),
        ("unifi_get_client_sessions", {"ap_mac": "aa:bb:cc:dd:ee:ff"}),
        ("unifi_get_client_details", {"mac_address": "aa:bb:cc:dd:ee:ff", "client_mac": "11:22:33:44:55:66"}),
        ("unifi_list_networks", {"mac_address": "aa:bb:cc:dd:ee:ff"}),
    ],
)
async def test_mac_hint_is_absent_when_not_applicable(mac_manifest: pathlib.Path, tool: str, args: dict) -> None:
    server = StrictKwargFastMCP("test", tools_manifest_path=mac_manifest)
    with pytest.raises(ToolError) as excinfo:
        await server.call_tool(tool, args)
    assert "takes the MAC address as" not in str(excinfo.value)


async def test_mac_hint_does_not_disturb_the_rest_of_the_message(mac_manifest: pathlib.Path) -> None:
    server = StrictKwargFastMCP("test", tools_manifest_path=mac_manifest)
    with pytest.raises(ToolError) as excinfo:
        await server.call_tool("unifi_get_client_sessions", {"client_mac": "aa:bb:cc:dd:ee:ff", "bogus": 1})
    assert str(excinfo.value) == (
        "Invalid params for 'unifi_get_client_sessions': "
        "unknown arguments {bogus, client_mac}. "
        "Valid arguments: [limit, mac_address]. "
        "'unifi_get_client_sessions' takes the MAC address as 'mac_address'."
    )
