"""Packaged API action catalog registry tests."""

from __future__ import annotations

import json

import pytest
from unifi_api.services import manifest
from unifi_api.services.manifest import CatalogLoadError, ManifestRegistry, ToolNotFound


def _catalog(*actions: dict, schema_version: int = 1) -> str:
    return json.dumps(
        {
            "schema_version": schema_version,
            "generated_by": "scripts/generate_api_action_catalog.py",
            "actions": list(actions),
            "excluded": [],
        }
    )


def _action(**changes) -> dict:
    action = {
        "name": "unifi_list_clients",
        "product": "network",
        "category": "clients",
        "permission_action": "read",
        "read_only_hint": True,
        "manager_attr": "client_manager",
        "manager_method": "get_clients",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    }
    action.update(changes)
    return action


def test_loads_packaged_catalog_with_manager_binding(monkeypatch) -> None:
    monkeypatch.setattr(manifest, "_read_catalog_resource", lambda: _catalog(_action()))

    registry = ManifestRegistry.load()

    entry = registry.resolve("unifi_list_clients")
    assert entry.product == "network"
    assert entry.permission_action == "read"
    assert entry.read_only_hint is True
    assert entry.manager_attr == "client_manager"
    assert entry.manager_method == "get_clients"
    assert entry.input_schema == {"type": "object", "properties": {}, "additionalProperties": False}


def test_real_packaged_catalog_has_all_product_sentinels() -> None:
    registry = ManifestRegistry.load()

    assert len(registry) == 271
    assert registry.has("unifi_list_clients")
    assert registry.has("protect_list_cameras")
    assert registry.has("access_list_doors")
    assert not registry.has("unifi_subscribe_events")


def test_unknown_tool_raises() -> None:
    registry = ManifestRegistry({})

    with pytest.raises(ToolNotFound):
        registry.resolve("definitely_not_a_real_tool_name_xyz")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("not json", "invalid JSON"),
        (json.dumps([]), "top level must be an object"),
        (_catalog(_action(), schema_version=2), "unsupported schema_version"),
        (json.dumps({"schema_version": 1, "actions": {}}), "actions must be an array"),
        (_catalog(_action(name="")), r"actions\[0\].name"),
        (_catalog(_action(product="wireless")), r"actions\[0\].product"),
        (_catalog(_action(read_only_hint="true")), r"actions\[0\].read_only_hint"),
        (_catalog(_action(permission_action="update", read_only_hint=True)), "conflicting safety metadata"),
        (_catalog(_action(manager_attr="")), r"actions\[0\].manager_attr"),
        (_catalog(_action(manager_method="")), r"actions\[0\].manager_method"),
        (_catalog(_action(input_schema=[])), r"actions\[0\].input_schema"),
        (_catalog(_action(input_schema={"type": "array"})), r"actions\[0\].input_schema.type"),
        (_catalog(_action(), _action()), "duplicate action name"),
    ],
)
def test_invalid_catalog_fails_closed(monkeypatch, raw: str, expected: str) -> None:
    monkeypatch.setattr(manifest, "_read_catalog_resource", lambda: raw)

    with pytest.raises(CatalogLoadError, match=expected):
        ManifestRegistry.load()


def test_missing_packaged_catalog_fails_closed(monkeypatch) -> None:
    def missing() -> str:
        raise FileNotFoundError("action_catalog.json")

    monkeypatch.setattr(manifest, "_read_catalog_resource", missing)

    with pytest.raises(CatalogLoadError, match="action_catalog.json"):
        ManifestRegistry.load()


def test_loader_reads_only_the_unifi_api_package(monkeypatch) -> None:
    requested: list[str] = []

    class FakeResource:
        def __truediv__(self, name: str):
            assert name == "action_catalog.json"
            return self

        def read_text(self) -> str:
            return _catalog(_action())

    def fake_files(package: str):
        requested.append(package)
        return FakeResource()

    monkeypatch.setattr(manifest, "files", fake_files)

    registry = ManifestRegistry.load()

    assert len(registry) == 1
    assert requested == ["unifi_api"]
