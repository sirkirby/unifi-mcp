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


@pytest.mark.parametrize("requirement", ["local_only", "api_key_only", "either", "both"])
def test_auth_requirements_survive_catalog_loading(monkeypatch, requirement):
    monkeypatch.setattr(manifest, "_read_catalog_resource", lambda: _catalog(_action(auth_method=requirement)))
    assert ManifestRegistry.load().resolve("unifi_list_clients").auth_method == requirement


@pytest.mark.parametrize("requirement", ["invalid", None, []])
def test_invalid_auth_requirement_fails_catalog_loading(monkeypatch, requirement):
    monkeypatch.setattr(manifest, "_read_catalog_resource", lambda: _catalog(_action(auth_method=requirement)))
    with pytest.raises(CatalogLoadError, match="auth_method"):
        ManifestRegistry.load()


def test_real_packaged_catalog_has_all_product_sentinels() -> None:
    registry = ManifestRegistry.load()

    assert len(registry) == 330
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


def test_account_catalog_requires_all_nine_read_only_api_key_bindings():
    from tests.sitemanager_data import CASES

    registry = ManifestRegistry.load()
    cloud = [registry.resolve(name) for name in registry.all_tools() if name.startswith("sitemanager_")]
    assert len(cloud) == 9
    assert {entry.name for entry in cloud} == {case[0] for case in CASES}
    for entry in cloud:
        assert entry.connection_kind == "sitemanager_account"
        assert entry.permission_action == "read" and entry.read_only_hint is True
        assert entry.auth_method == "api_key_only"
    assert not any("support_bundle" in entry.name or "connection" in entry.name for entry in cloud)


@pytest.mark.parametrize(
    "change",
    [
        {"connection_kind": "controller"},
        {"connection_kind": None},
        {"auth_method": "both"},
        {"permission_action": "update", "read_only_hint": False},
        {"product": "network"},
    ],
)
def test_mismatched_account_metadata_fails_closed(monkeypatch, change):
    value = _action(
        name="sitemanager_list_hosts",
        product="sitemanager",
        category="hosts",
        manager_attr="inventory_manager",
        manager_method="list_hosts",
        auth_method="api_key_only",
        connection_kind="sitemanager_account",
        **{},
    )
    value.update(change)
    monkeypatch.setattr(manifest, "_read_catalog_resource", lambda: _catalog(value))
    with pytest.raises(CatalogLoadError):
        ManifestRegistry.load()


def test_account_connection_kind_cannot_default_to_controller(monkeypatch):
    value = _action(name="sitemanager_list_hosts", product="sitemanager", auth_method="api_key_only")
    monkeypatch.setattr(manifest, "_read_catalog_resource", lambda: _catalog(value))
    with pytest.raises(CatalogLoadError, match="connection_kind"):
        ManifestRegistry.load()


INNERSPACE_READS = {
    "innerspace_get_plan_asset",
    "innerspace_get_project",
    "innerspace_get_status",
    "innerspace_list_access_points",
    "innerspace_list_floor_plans",
    "innerspace_list_inventory",
    "innerspace_list_placed_devices",
    "innerspace_list_switches",
    "innerspace_list_walls",
}
# tool -> (permission_action, read_only_hint)
INNERSPACE_WRITES = {
    "innerspace_create_walls": ("create", False),
    "innerspace_update_walls": ("update", False),
    "innerspace_remove_walls": ("delete", False),
    "innerspace_create_wall_type": ("create", False),
    "innerspace_update_wall_type": ("update", False),
    "innerspace_create_attenuation_objects": ("create", False),
    "innerspace_update_attenuation_objects": ("update", False),
    "innerspace_remove_attenuation_objects": ("delete", False),
    "innerspace_create_attenuation_object_type": ("create", False),
    "innerspace_update_attenuation_object_type": ("update", False),
    "innerspace_rename_floor_plan": ("update", False),
    "innerspace_set_floor_attenuation": ("update", False),
    "innerspace_reorder_floor_plans": ("update", False),
    "innerspace_set_plan_scale": ("delete", False),
    "innerspace_set_project_unit": ("update", False),
}


def test_innerspace_catalog_entries_are_session_actions() -> None:
    registry = ManifestRegistry.load()
    entries = {name: registry.resolve(name) for name in registry.all_tools() if name.startswith("innerspace_")}
    expected = {**{name: ("read", True) for name in INNERSPACE_READS}, **INNERSPACE_WRITES}

    assert len(entries) == 9 + 15
    assert {name: (entry.permission_action, entry.read_only_hint) for name, entry in entries.items()} == expected
    for entry in entries.values():
        assert entry.product == "innerspace"
        assert entry.connection_kind == "controller"
        assert entry.auth_method == "local_only"


@pytest.mark.parametrize("action,read_only_hint", [("read", True), ("create", False), ("delete", False)])
@pytest.mark.parametrize("auth_method", ["either", "api_key_only", "both"])
def test_innerspace_catalog_refuses_anything_but_session_actions(
    monkeypatch, action, read_only_hint, auth_method
) -> None:
    entry = _action(
        name="innerspace_get_status",
        product="innerspace",
        manager_attr="system_manager",
        manager_method="get_status",
        permission_action=action,
        read_only_hint=read_only_hint,
        auth_method=auth_method,
    )
    monkeypatch.setattr(manifest, "_read_catalog_resource", lambda: _catalog(entry))

    with pytest.raises(CatalogLoadError, match="session InnerSpace operation"):
        ManifestRegistry.load()


@pytest.mark.parametrize("action,read_only_hint", [("read", True), ("update", False), ("delete", False)])
def test_innerspace_catalog_accepts_session_reads_and_writes(monkeypatch, action, read_only_hint) -> None:
    entry = _action(
        name="innerspace_get_status",
        product="innerspace",
        manager_attr="system_manager",
        manager_method="get_status",
        permission_action=action,
        read_only_hint=read_only_hint,
    )
    monkeypatch.setattr(manifest, "_read_catalog_resource", lambda: _catalog(entry))

    assert ManifestRegistry.load().resolve("innerspace_get_status").permission_action == action


DRIVE_READS = {
    "drive_get_file_services",
    "drive_get_shared_drive",
    "drive_get_system_info",
    "drive_list_disks",
    "drive_list_nfs_connections",
    "drive_list_shared_drives",
    "drive_list_storage_pools",
}
DRIVE_WRITES = {
    "drive_set_file_service": ("file_service", "update", "set_file_service"),
    "drive_add_nfs_connection": ("nfs_connection", "create", "add_nfs_connection"),
    "drive_update_nfs_connection": ("nfs_connection", "update", "update_nfs_connection"),
    "drive_remove_nfs_connection": ("nfs_connection", "delete", "remove_nfs_connection"),
}


def test_drive_catalog_entries_are_session_reads_and_confirmed_writes() -> None:
    registry = ManifestRegistry.load()
    entries = {name: registry.resolve(name) for name in registry.all_tools() if name.startswith("drive_")}

    assert set(entries) == DRIVE_READS | set(DRIVE_WRITES)
    for name, entry in entries.items():
        assert entry.product == "drive"
        assert entry.connection_kind == "controller"
        assert entry.auth_method == "local_only"
        if name in DRIVE_READS:
            assert (entry.permission_action, entry.read_only_hint) == ("read", True)
        else:
            # The confirmed manager method: it plans from fresh state and applies in one call.
            category, action, method = DRIVE_WRITES[name]
            assert (entry.category, entry.permission_action, entry.read_only_hint) == (category, action, False)
            assert (entry.manager_attr, entry.manager_method) == ("file_service_manager", method)


@pytest.mark.parametrize("auth_method", ["either", "api_key_only"])
def test_drive_catalog_refuses_anything_but_session_operations(monkeypatch, auth_method) -> None:
    action = _action(
        name="drive_get_system_info",
        product="drive",
        manager_attr="system_manager",
        manager_method="get_system_info",
        auth_method=auth_method,
    )
    monkeypatch.setattr(manifest, "_read_catalog_resource", lambda: _catalog(action))

    with pytest.raises(CatalogLoadError, match="session Drive operation"):
        ManifestRegistry.load()
