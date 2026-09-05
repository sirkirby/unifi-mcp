"""The manifest generator emits argument_aliases per tool."""

from __future__ import annotations

from unifi_mcp_shared.manifest_generator import manifest_tool_entry
from unifi_mcp_shared.tool_index import ToolMetadata


def _meta(**overrides) -> ToolMetadata:
    base = dict(
        name="unifi_get_client_details",
        description="Look up a client.",
        title="Get Client Details",
        input_schema={"type": "object", "properties": {"mac_address": {"type": "string"}}},
    )
    base.update(overrides)
    return ToolMetadata(**base)


def test_entry_carries_argument_aliases() -> None:
    entry = manifest_tool_entry(_meta(argument_aliases={"device_mac": "mac_address"}), annotations=None)
    assert entry["argument_aliases"] == {"device_mac": "mac_address"}


def test_entry_omits_key_when_no_aliases() -> None:
    entry = manifest_tool_entry(_meta(), annotations=None)
    assert "argument_aliases" not in entry
    assert entry["name"] == "unifi_get_client_details"
    assert entry["schema"]["input"]["properties"] == {"mac_address": {"type": "string"}}


def test_entry_keeps_existing_fields() -> None:
    entry = manifest_tool_entry(
        _meta(permission_category="clients", permission_action="read", output_schema={"type": "object"}),
        annotations={"readOnlyHint": True},
    )
    assert entry["title"] == "Get Client Details"
    assert entry["annotations"] == {"readOnlyHint": True}
    assert entry["permission_category"] == "clients"
    assert entry["permission_action"] == "read"
    assert entry["schema"]["output"] == {"type": "object"}


def test_to_dict_includes_argument_aliases() -> None:
    assert _meta(argument_aliases={"mac": "mac_address"}).to_dict()["argument_aliases"] == {"mac": "mac_address"}
    assert "argument_aliases" not in _meta().to_dict()
