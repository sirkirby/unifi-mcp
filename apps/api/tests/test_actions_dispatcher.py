"""Action dispatcher unit tests with mocks."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from unifi_api.services.actions import (
    CapabilityMismatch,
    DispatchEntry,
    DispatchEntryMissing,
    build_dispatch_table,
    dispatch_action,
)
from unifi_api.services.manifest import ManifestRegistry, ToolEntry, ToolNotFound


def _registry_with(tool: ToolEntry) -> ManifestRegistry:
    return ManifestRegistry({tool.name: tool})


@pytest.mark.asyncio
async def test_dispatch_capability_mismatch_raises() -> None:
    entry = ToolEntry(
        name="unifi_list_clients",
        product="network",
        category="clients",
        manager="",
        method="",
    )
    registry = _registry_with(entry)
    factory = MagicMock()
    session = MagicMock()
    with pytest.raises(CapabilityMismatch):
        await dispatch_action(
            registry=registry,
            factory=factory,
            session=session,
            tool_name="unifi_list_clients",
            controller_id="cid",
            controller_products=["protect"],
            site="default",
            args={},
            confirm=False,
        )


@pytest.mark.asyncio
async def test_dispatch_unknown_tool_raises() -> None:
    registry = ManifestRegistry({})
    factory = MagicMock()
    session = MagicMock()
    with pytest.raises(ToolNotFound):
        await dispatch_action(
            registry=registry,
            factory=factory,
            session=session,
            tool_name="xxx",
            controller_id="cid",
            controller_products=["network"],
            site="default",
            args={},
            confirm=False,
        )


@pytest.mark.asyncio
async def test_dispatch_missing_table_entry_raises() -> None:
    entry = ToolEntry(
        name="unmapped_tool",
        product="network",
        category="clients",
        manager="",
        method="",
    )
    registry = _registry_with(entry)
    factory = MagicMock()
    session = MagicMock()
    # Empty dispatch table forces the missing-entry branch.
    with pytest.raises(DispatchEntryMissing):
        await dispatch_action(
            registry=registry,
            factory=factory,
            session=session,
            tool_name="unmapped_tool",
            controller_id="cid",
            controller_products=["network"],
            site="default",
            args={},
            confirm=False,
            dispatch_table={},
        )


@pytest.mark.asyncio
async def test_dispatch_happy_path_invokes_manager() -> None:
    entry = ToolEntry(
        name="unifi_list_clients",
        product="network",
        category="clients",
        manager="",
        method="",
    )
    registry = _registry_with(entry)

    # Mock domain manager whose `get_clients` returns a sentinel response.
    expected_response = {"success": True, "data": {"clients": []}}
    domain_manager = MagicMock()
    domain_manager.get_clients = AsyncMock(return_value=expected_response)

    # Mock connection manager — supports site updates.
    conn_manager = MagicMock()
    conn_manager.site = "default"
    conn_manager.set_site = AsyncMock()

    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=domain_manager)
    factory.get_connection_manager = AsyncMock(return_value=conn_manager)

    session = MagicMock()

    result = await dispatch_action(
        registry=registry,
        factory=factory,
        session=session,
        tool_name="unifi_list_clients",
        controller_id="cid",
        controller_products=["network"],
        site="default",  # same as conn.site -> no set_site call
        args={},
        confirm=False,
        dispatch_table={
            "unifi_list_clients": DispatchEntry(
                manager_attr="client_manager", method="get_clients"
            ),
        },
    )

    assert result is expected_response
    factory.get_domain_manager.assert_awaited_once_with(
        session=session,
        controller_id="cid",
        product="network",
        attr_name="client_manager",
    )
    domain_manager.get_clients.assert_awaited_once_with()
    # Same site -> no set_site call.
    conn_manager.set_site.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_updates_site_when_changed() -> None:
    entry = ToolEntry(
        name="unifi_list_clients",
        product="network",
        category="clients",
        manager="",
        method="",
    )
    registry = _registry_with(entry)

    domain_manager = MagicMock()
    domain_manager.get_clients = AsyncMock(return_value={"ok": True})

    conn_manager = MagicMock()
    conn_manager.site = "default"
    conn_manager.set_site = AsyncMock()

    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=domain_manager)
    factory.get_connection_manager = AsyncMock(return_value=conn_manager)

    await dispatch_action(
        registry=registry,
        factory=factory,
        session=MagicMock(),
        tool_name="unifi_list_clients",
        controller_id="cid",
        controller_products=["network"],
        site="upstairs",
        args={"limit": 10},
        confirm=False,
        dispatch_table={
            "unifi_list_clients": DispatchEntry(
                manager_attr="client_manager", method="get_clients"
            ),
        },
    )

    conn_manager.set_site.assert_awaited_once_with("upstairs")
    domain_manager.get_clients.assert_awaited_once_with(limit=10)


def test_build_dispatch_table_finds_real_tools() -> None:
    """Smoke test that AST introspection recovers at least a known mapping.

    The repo ships network/protect/access tool modules; we expect the
    dispatch table to contain at least one well-known tool from each.
    """
    table = build_dispatch_table()
    # unifi_list_clients -> client_manager.get_clients (PR4 override pins the
    # default-path branch where include_offline=False).
    network_entry = table.get("unifi_list_clients") or table.get("list_clients")
    assert network_entry is not None
    assert network_entry.manager_attr == "client_manager"
    assert network_entry.method == "get_clients"

    # protect_list_cameras -> camera_manager.list_cameras
    protect_entry = table.get("protect_list_cameras")
    assert protect_entry is not None
    assert protect_entry.manager_attr == "camera_manager"
    assert protect_entry.method == "list_cameras"

    # access_list_doors -> door_manager.list_doors
    access_entry = table.get("access_list_doors")
    assert access_entry is not None
    assert access_entry.manager_attr == "door_manager"
    assert access_entry.method == "list_doors"


def test_dispatch_overrides_redirect_compose_tools_to_mutation() -> None:
    """PR4: tools whose body has 2+ awaits by design route to the mutation
    method via the static DISPATCH_OVERRIDES table — not the AST-captured
    first-await (typically a lookup or preview)."""
    from unifi_api.services.dispatch_overrides import DISPATCH_OVERRIDES

    table = build_dispatch_table()

    # Every override must be present in the resolved table and match.
    for tool_name, (manager_attr, method) in DISPATCH_OVERRIDES.items():
        entry = table.get(tool_name)
        assert entry is not None, f"override missing from dispatch table: {tool_name}"
        assert entry.manager_attr == manager_attr, (
            f"{tool_name} manager: got {entry.manager_attr!r}, want {manager_attr!r}"
        )
        assert entry.method == method, (
            f"{tool_name} method: got {entry.method!r}, want {method!r}"
        )


def test_dispatch_overrides_specific_targets() -> None:
    """Spot-check: previously-broken dispatch for a representative sample
    of each override category now resolves to the mutation method."""
    table = build_dispatch_table()

    # Network lookup-then-act with state-dependent preview
    assert table["unifi_block_client"].method == "block_client"
    assert table["unifi_update_network"].method == "update_network"
    assert table["unifi_toggle_wlan"].method == "toggle_wlan"
    # Toggle that needs current state
    assert table["unifi_toggle_firewall_policy"].method == "toggle_firewall_policy"
    # Stats: list-returning method (was AST-captured as get_X_details, a dict)
    assert table["unifi_get_device_stats"].manager_attr == "stats_manager"
    assert table["unifi_get_device_stats"].method == "get_device_stats"
    assert table["unifi_get_client_stats"].method == "get_client_stats"

    # Protect preview/execute split
    assert table["protect_reboot_camera"].method == "apply_reboot_camera"
    assert table["protect_alarm_arm"].method == "arm"
    assert table["protect_acknowledge_event"].method == "apply_acknowledge_event"

    # Access preview/execute split
    assert table["access_lock_door"].method == "apply_lock_door"
    assert table["access_create_credential"].method == "apply_create_credential"
    assert table["access_update_policy"].method == "apply_update_policy"
