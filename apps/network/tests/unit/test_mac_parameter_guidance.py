"""Network subject MACs use mac_address; the distinct RF scan AP uses ap_mac."""

from __future__ import annotations

import json
import pathlib

import pytest

MANIFEST = pathlib.Path(__file__).resolve().parents[2] / "src" / "unifi_network_mcp" / "tools_manifest.json"


@pytest.fixture(scope="module")
def descriptions() -> dict[str, str]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {tool["name"]: tool.get("description", "") for tool in data["tools"]}


@pytest.mark.parametrize(
    ("tool", "expected"),
    [
        ("unifi_list_clients", ("mac_address", "unifi_get_client_sessions", "unifi_get_client_details")),
        ("unifi_list_devices", ("mac_address", "ap_mac", "unifi_get_switch_ports")),
        ("unifi_list_blocked_clients", ("mac_address", "unifi_unblock_client")),
    ],
)
def test_list_description_names_the_next_call_parameter(
    descriptions: dict[str, str], tool: str, expected: tuple[str, ...]
) -> None:
    description = descriptions[tool]
    for token in expected:
        assert token in description, f"{tool} description does not mention {token}"


@pytest.mark.parametrize(
    ("tool", "parameter"),
    [
        ("unifi_get_client_details", "mac_address"),
        ("unifi_get_client_sessions", "mac_address"),
        ("unifi_get_switch_ports", "mac_address"),
        ("unifi_unblock_client", "mac_address"),
        ("unifi_get_device_details", "mac_address"),
    ],
)
def test_the_named_parameters_are_the_real_ones(tool: str, parameter: str) -> None:
    """A description that names a parameter the tool does not take is worse than none."""
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entry = next(t for t in data["tools"] if t["name"] == tool)
    assert parameter in entry["schema"]["input"]["properties"]


def test_every_tool_named_in_those_descriptions_exists(descriptions: dict[str, str]) -> None:
    """A description that points at a tool this server does not have sends a caller nowhere."""
    import re

    known = set(descriptions)
    for tool in ("unifi_list_clients", "unifi_list_devices", "unifi_list_blocked_clients"):
        named = set(re.findall(r"\bunifi_[a-z0-9_]+", descriptions[tool])) - {tool}
        assert named, f"{tool} names no follow-up tool"
        assert named <= known, f"{tool} names tools that do not exist: {sorted(named - known)}"


@pytest.mark.parametrize("tool", ["unifi_list_clients", "unifi_list_devices", "unifi_list_blocked_clients"])
def test_the_registered_description_matches_the_manifest(descriptions: dict[str, str], tool: str) -> None:
    """The two are both live: eager registration serves the decorator string, lazy mode
    serves the manifest. A description edited in one and not regenerated into the other
    would leave half the callers reading the old text."""
    import unifi_network_mcp.tools.clients  # noqa: F401
    import unifi_network_mcp.tools.devices  # noqa: F401
    from unifi_network_mcp.runtime import server

    registered = server._tool_manager.get_tool(tool)
    assert registered.description == descriptions[tool]


def test_every_mac_spelling_in_use_is_named_by_one_of_the_descriptions(descriptions: dict[str, str]) -> None:
    """The descriptions enumerate parameter names, so they read as exhaustive. A fifth
    spelling appearing on some tool and named nowhere is worse than no enumeration."""
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    spellings = {"mac", "mac_address", "client_mac", "device_mac", "ap_mac"}
    in_use = set()
    for entry in data["tools"]:
        in_use |= spellings & set(entry.get("schema", {}).get("input", {}).get("properties", {}))

    named = " ".join(descriptions[t] for t in ("unifi_list_clients", "unifi_list_devices"))
    missing = sorted(name for name in in_use if name not in named)

    assert in_use, "no MAC parameters found at all; the manifest fixture is wrong"
    assert in_use == {"mac_address", "ap_mac"}
    assert not missing, f"no list description names {missing}"
