"""Manifest lookup table tests."""

import pytest
from unifi_api.services.manifest import ManifestRegistry, ToolNotFound


def test_loads_manifests_from_apps() -> None:
    reg = ManifestRegistry.load_from_apps()
    assert reg.has("unifi_list_clients") or reg.has("list_clients")
    # At least one well-known tool from each product should be present
    has_network = reg.has("unifi_list_clients") or reg.has("unifi_list_devices")
    has_protect = reg.has("protect_list_cameras") or reg.has("list_cameras")
    has_access = reg.has("access_list_doors") or reg.has("list_doors")
    assert has_network, "expected at least one network tool"
    assert has_protect, "expected at least one protect tool"
    assert has_access, "expected at least one access tool"


def test_resolves_returns_tool_entry() -> None:
    reg = ManifestRegistry.load_from_apps()
    name = "unifi_list_clients" if reg.has("unifi_list_clients") else _some_known_network(reg)[0]
    entry = reg.resolve(name)
    assert entry.name == name
    assert entry.product == "network"


def test_unknown_tool_raises() -> None:
    reg = ManifestRegistry.load_from_apps()
    with pytest.raises(ToolNotFound):
        reg.resolve("definitely_not_a_real_tool_name_xyz")


def _some_known_network(reg) -> list[str]:
    """Helper: fall back to any tool that resolves and has product=network."""
    for name in ("unifi_list_clients", "unifi_list_devices", "list_clients", "list_devices"):
        if reg.has(name):
            return [name]
    raise RuntimeError("no recognizable network tool in manifest")
