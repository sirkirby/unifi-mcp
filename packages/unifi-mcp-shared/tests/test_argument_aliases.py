"""Tests for argument alias rewriting at the MCP dispatch boundary."""

from __future__ import annotations

import logging
import pathlib
from unittest.mock import AsyncMock, patch

import pytest
from mcp.server.mcpserver import MCPServer as FastMCP
from mcp.server.mcpserver.exceptions import ToolError
from unifi_core.redaction import REDACTED
from unifi_mcp_shared.argument_aliases import (
    MAC_SPELLINGS,
    ArgumentAliasMixin,
    append_argument_alias_note,
    argument_alias_note,
    argument_aliases_from_manifest,
    load_argument_aliases,
    mac_aliases,
    validate_argument_aliases,
)
from unifi_mcp_shared.strict_dispatch import StrictKwargFastMCP

from .manifest_fixtures import make_tool as _make_tool
from .manifest_fixtures import write_manifest as _write_manifest


@pytest.fixture
def mac_manifest(tmp_path: pathlib.Path) -> pathlib.Path:
    tools = [
        _make_tool(
            "unifi_get_client_details",
            {"mac_address": {"type": "string"}},
            mac_aliases("mac_address"),
        ),
        _make_tool(
            "unifi_trigger_rf_scan",
            {"ap_mac": {"type": "string"}, "confirm": {"type": "boolean"}},
            mac_aliases("ap_mac"),
        ),
        _make_tool("unifi_list_devices", {"site": {"type": "string"}}),
    ]
    return _write_manifest(tmp_path, tools)


# --- helpers -----------------------------------------------------------------


def test_mac_spellings_lists_canonical_first() -> None:
    assert MAC_SPELLINGS[0] == "mac_address"
    assert set(MAC_SPELLINGS) == {"mac_address", "device_mac", "client_mac", "mac"}


def test_mac_aliases_maps_every_other_spelling_to_canonical() -> None:
    assert mac_aliases("mac_address") == {
        "device_mac": "mac_address",
        "client_mac": "mac_address",
        "mac": "mac_address",
    }
    assert mac_aliases("device_mac") == {"mac_address": "device_mac", "client_mac": "device_mac", "mac": "device_mac"}


def test_mac_aliases_for_a_non_standard_parameter_maps_all_spellings() -> None:
    assert mac_aliases("ap_mac") == {spelling: "ap_mac" for spelling in MAC_SPELLINGS}


def test_argument_alias_note_groups_by_canonical() -> None:
    note = argument_alias_note(mac_aliases("mac_address"))
    assert note == (
        "Argument aliases: device_mac, client_mac, mac are accepted for mac_address "
        "(deprecated spellings; prefer mac_address)."
    )


def test_append_note_closes_an_unterminated_description_first() -> None:
    assert append_argument_alias_note("Block a client by MAC address", {"mac": "mac_address"}) == (
        "Block a client by MAC address. Argument aliases: mac is accepted for mac_address "
        "(deprecated spelling; prefer mac_address)."
    )
    assert append_argument_alias_note("Done.", {"mac": "mac_address"}).startswith("Done. Argument aliases:")
    assert append_argument_alias_note("", {"mac": "mac_address"}).startswith("Argument aliases:")


def test_validate_rejects_alias_that_collides_with_a_parameter() -> None:
    with pytest.raises(ValueError, match="collides"):
        validate_argument_aliases("t", {"device_mac": "mac_address"}, {"mac_address": {}, "device_mac": {}})


def test_validate_rejects_confirm_as_a_target() -> None:
    with pytest.raises(ValueError, match="confirmation parameter"):
        validate_argument_aliases("t", {"yes": "confirm"}, {"confirm": {}, "mac_address": {}})


def test_validate_rejects_missing_canonical() -> None:
    with pytest.raises(ValueError, match="mac_address"):
        validate_argument_aliases("t", {"device_mac": "mac_address"}, {"site": {}})


def test_validate_rejects_sensitive_alias_for_non_sensitive_canonical() -> None:
    with pytest.raises(ValueError, match="sensitive"):
        validate_argument_aliases("t", {"password": "label"}, {"label": {}})


def test_validate_allows_sensitive_alias_for_sensitive_canonical() -> None:
    assert validate_argument_aliases("t", {"password": "x_password"}, {"x_password": {}}) == {"password": "x_password"}


def test_validate_rejects_non_string_entries() -> None:
    with pytest.raises(ValueError):
        validate_argument_aliases("t", {"device_mac": 3}, {"mac_address": {}})  # type: ignore[dict-item]


# --- manifest loading ----------------------------------------------------------


def test_load_reads_aliases_per_tool(mac_manifest: pathlib.Path) -> None:
    aliases = load_argument_aliases(mac_manifest)
    assert aliases["unifi_get_client_details"] == mac_aliases("mac_address")
    assert aliases["unifi_trigger_rf_scan"] == mac_aliases("ap_mac")
    assert "unifi_list_devices" not in aliases


def test_load_drops_malformed_entries_and_warns(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    tools = [
        _make_tool("collides", {"mac_address": {}, "device_mac": {}}, {"device_mac": "mac_address"}),
        _make_tool("missing_canonical", {"site": {}}, {"device_mac": "mac_address"}),
        _make_tool("not_a_dict", {"mac_address": {}}, ["device_mac"]),
        _make_tool("fine", {"mac_address": {}}, {"device_mac": "mac_address"}),
    ]
    path = _write_manifest(tmp_path, tools)
    with caplog.at_level(logging.WARNING):
        aliases = load_argument_aliases(path)
    assert aliases == {"fine": {"device_mac": "mac_address"}}
    dropped = [r.getMessage() for r in caplog.records if "argument_aliases" in r.getMessage()]
    assert len(dropped) == 3


def test_load_missing_manifest_returns_empty(tmp_path: pathlib.Path) -> None:
    assert load_argument_aliases(tmp_path / "nope.json") == {}


def test_from_manifest_ignores_non_manifests() -> None:
    assert argument_aliases_from_manifest(None) == {}
    assert argument_aliases_from_manifest({"tools": "nope"}) == {}
    assert argument_aliases_from_manifest([]) == {}


def test_from_manifest_drops_entry_with_null_input_schema(caplog: pytest.LogCaptureFixture) -> None:
    manifest = {"tools": [{"name": "t", "schema": {"input": None}, "argument_aliases": {"device_mac": "mac_address"}}]}
    with caplog.at_level(logging.WARNING):
        assert argument_aliases_from_manifest(manifest) == {}
    assert any("dropping argument_aliases for t" in r.getMessage() for r in caplog.records)


# --- dispatch ----------------------------------------------------------------


async def test_alias_rewritten_before_strict_check(mac_manifest: pathlib.Path) -> None:
    server = StrictKwargFastMCP("test", tools_manifest_path=mac_manifest)
    sentinel = [{"type": "text", "text": "ok"}]
    with patch.object(FastMCP, "call_tool", new=AsyncMock(return_value=sentinel)) as super_mock:
        result = await server.call_tool("unifi_get_client_details", {"device_mac": "aa:bb:cc:dd:ee:ff"})
    assert result is sentinel
    super_mock.assert_awaited_once_with("unifi_get_client_details", {"mac_address": "aa:bb:cc:dd:ee:ff"}, context=None)


async def test_every_spelling_rewrites_to_non_standard_canonical(mac_manifest: pathlib.Path) -> None:
    server = StrictKwargFastMCP("test", tools_manifest_path=mac_manifest)
    with patch.object(FastMCP, "call_tool", new=AsyncMock(return_value=None)) as super_mock:
        await server.call_tool("unifi_trigger_rf_scan", {"mac": "aa:bb:cc:dd:ee:ff", "confirm": True})
    super_mock.assert_awaited_once_with(
        "unifi_trigger_rf_scan", {"confirm": True, "ap_mac": "aa:bb:cc:dd:ee:ff"}, context=None
    )


async def test_alias_and_canonical_together_conflict(mac_manifest: pathlib.Path) -> None:
    server = StrictKwargFastMCP("test", tools_manifest_path=mac_manifest)
    with pytest.raises(ToolError) as excinfo:
        await server.call_tool("unifi_get_client_details", {"device_mac": "aa", "mac_address": "bb"})
    assert str(excinfo.value) == (
        "Invalid params for 'unifi_get_client_details': device_mac, mac_address name the same argument; "
        "pass only mac_address."
    )


async def test_two_aliases_together_conflict(mac_manifest: pathlib.Path) -> None:
    server = StrictKwargFastMCP("test", tools_manifest_path=mac_manifest)
    with pytest.raises(ToolError, match="client_mac, device_mac name the same argument; pass only mac_address"):
        await server.call_tool("unifi_get_client_details", {"device_mac": "aa", "client_mac": "bb"})


async def test_undeclared_alias_is_still_unknown(mac_manifest: pathlib.Path) -> None:
    server = StrictKwargFastMCP("test", tools_manifest_path=mac_manifest)
    with pytest.raises(ToolError, match="unknown arguments {device_mac}"):
        await server.call_tool("unifi_list_devices", {"device_mac": "aa"})


async def test_caller_arguments_not_mutated(mac_manifest: pathlib.Path) -> None:
    server = StrictKwargFastMCP("test", tools_manifest_path=mac_manifest)
    arguments = {"device_mac": "aa:bb:cc:dd:ee:ff"}
    with patch.object(FastMCP, "call_tool", new=AsyncMock(return_value=None)):
        await server.call_tool("unifi_get_client_details", arguments)
    assert arguments == {"device_mac": "aa:bb:cc:dd:ee:ff"}


async def test_arguments_without_aliases_pass_through_same_object(mac_manifest: pathlib.Path) -> None:
    server = StrictKwargFastMCP("test", tools_manifest_path=mac_manifest)
    arguments = {"mac_address": "aa:bb:cc:dd:ee:ff"}
    with patch.object(FastMCP, "call_tool", new=AsyncMock(return_value=None)) as super_mock:
        await server.call_tool("unifi_get_client_details", arguments)
    assert super_mock.await_args.args[1] is arguments


async def test_alias_is_rewritten_before_the_marker_guard(tmp_path: pathlib.Path) -> None:
    """A benign alias may target a sensitive canonical; the marker guard must see the canonical name."""
    path = _write_manifest(
        tmp_path,
        [_make_tool("unifi_set_secret", {"x_password": {"type": "string"}}, {"nickname": "x_password"})],
    )
    server = StrictKwargFastMCP("test", tools_manifest_path=path)
    with pytest.raises(ToolError, match="x_password is the redaction marker"):
        await server.call_tool("unifi_set_secret", {"nickname": REDACTED})


def test_strict_server_holds_aliases_on_the_mixin(mac_manifest: pathlib.Path) -> None:
    """The alias state is the mixin's, loaded from the same manifest parse as the strict guard."""
    server = StrictKwargFastMCP("test", tools_manifest_path=mac_manifest)
    assert isinstance(server, ArgumentAliasMixin)
    assert server._argument_aliases["unifi_trigger_rf_scan"] == mac_aliases("ap_mac")


def test_server_without_manifest_has_no_aliases() -> None:
    server = StrictKwargFastMCP("test")
    assert server.apply_argument_aliases("anything", {"device_mac": "aa"}) == {"device_mac": "aa"}
