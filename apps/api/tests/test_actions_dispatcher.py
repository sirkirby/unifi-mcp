"""Action dispatcher unit tests with mocks."""

from __future__ import annotations

import base64
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_api.services.action_results import ShapedReadResult
from unifi_api.services.actions import (
    CapabilityMismatch,
    DispatchEntry,
    DispatchEntryMissing,
    MutationPreview,
    build_dispatch_table,
    dispatch_action,
)
from unifi_api.services.dispatch_overrides import DISPATCH_ARG_TRANSLATORS, DISPATCH_RESULT_ADAPTERS
from unifi_api.services.manifest import ManifestRegistry, ToolEntry, ToolNotFound
from unifi_core.redaction import REDACTED

PRODUCTION_REGISTRY = ManifestRegistry.load()


def _registry_with(tool: ToolEntry) -> ManifestRegistry:
    if tool.read_only_hint is None and PRODUCTION_REGISTRY.has(tool.name):
        production_entry = PRODUCTION_REGISTRY.resolve(tool.name)
        tool = replace(
            tool,
            manager=production_entry.manager,
            method=production_entry.method,
            permission_action=production_entry.permission_action,
            read_only_hint=production_entry.read_only_hint,
        )
    return ManifestRegistry({tool.name: tool})


@pytest.mark.asyncio
async def test_catalog_binding_is_authoritative_and_accepts_sync_result() -> None:
    entry = ToolEntry(
        name="unifi_get_event_types",
        product="network",
        category="events",
        manager="event_manager",
        method="get_event_type_prefixes",
        permission_action="read",
        read_only_hint=True,
    )
    manager = MagicMock()
    manager.get_event_type_prefixes.return_value = {"EVT_WU_": "wireless"}
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)
    connection = MagicMock(site="default")
    factory.get_connection_manager = AsyncMock(return_value=connection)
    session = MagicMock()

    result = await dispatch_action(
        registry=ManifestRegistry({entry.name: entry}),
        factory=factory,
        session=session,
        tool_name=entry.name,
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args={},
        confirm=False,
    )

    assert result == {"EVT_WU_": "wireless"}
    factory.get_domain_manager.assert_awaited_once_with(
        session=session,
        controller_id="cid",
        product="network",
        attr_name="event_manager",
        site="default",
    )
    manager.get_event_type_prefixes.assert_called_once_with()


def _dispatchable_entries() -> list[tuple[str, ToolEntry]]:
    table = build_dispatch_table()
    return [
        (tool_name, PRODUCTION_REGISTRY.resolve(tool_name))
        for tool_name in PRODUCTION_REGISTRY.all_tools()
        if tool_name in table
    ]


DISPATCHABLE_ENTRIES = _dispatchable_entries()
DISPATCHABLE_MUTATIONS = [
    (tool_name, entry)
    for tool_name, entry in DISPATCHABLE_ENTRIES
    if entry.permission_action in {"create", "update", "delete"}
]


def test_every_dispatchable_entry_has_consistent_safety_metadata() -> None:
    assert DISPATCHABLE_ENTRIES
    for tool_name, entry in DISPATCHABLE_ENTRIES:
        if entry.permission_action in {"create", "update", "delete"}:
            assert entry.read_only_hint is False, tool_name
        else:
            assert entry.permission_action in {"", "read"}, tool_name
            assert entry.read_only_hint is True, tool_name


def test_dispatchable_mutations_include_high_impact_sentinels() -> None:
    mutation_names = {tool_name for tool_name, _entry in DISPATCHABLE_MUTATIONS}
    assert {
        "access_unlock_door",
        "access_lock_door",
        "access_reboot_device",
        "access_create_credential",
        "protect_reboot_camera",
        "protect_toggle_recording",
        "unifi_reboot_device",
        "unifi_power_cycle_port",
    } <= mutation_names


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "entry"),
    DISPATCHABLE_MUTATIONS,
    ids=[tool_name for tool_name, _entry in DISPATCHABLE_MUTATIONS],
)
async def test_every_dispatchable_mutation_preview_never_resolves_manager(
    tool_name: str,
    entry: ToolEntry,
) -> None:
    factory = MagicMock()

    try:
        result = await dispatch_action(
            registry=_registry_with(entry),
            factory=factory,
            session=MagicMock(),
            tool_name=tool_name,
            controller_id="cid",
            controller_products=[entry.product],
            site="default",
            args={},
            confirm=False,
        )
    except ValueError:
        # Most production mutations require arguments. Validation may reject
        # this deliberately minimal probe, but it must still fail before a
        # controller manager is resolved.
        pass
    else:
        assert isinstance(result, MutationPreview)

    factory.get_domain_manager.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_capability_mismatch_raises() -> None:
    entry = ToolEntry(
        name="unifi_list_clients",
        product="network",
        category="clients",
        manager="",
        method="",
        permission_action="read",
        read_only_hint=True,
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
        permission_action="read",
        read_only_hint=True,
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

    # Mock domain manager whose `get_clients` returns controller rows.
    expected_response: list[dict[str, object]] = []
    domain_manager = MagicMock()
    domain_manager._connection.site = "default"
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
            "unifi_list_clients": DispatchEntry(manager_attr="client_manager", method="get_clients"),
        },
    )

    assert result == ShapedReadResult(
        payload={
            "success": True,
            "site": "default",
            "filter_type": "all",
            "search": None,
            "fields": None,
            "total_count": 0,
            "returned_count": 0,
            "count": 0,
            "limit": 100,
            "clients": [],
        },
        data_key="clients",
        render_hint={
            "primary_key": "mac",
            "display_columns": ["name", "ip", "connection_type", "status"],
            "sort_default": "name:asc",
        },
    )
    factory.get_domain_manager.assert_awaited_once_with(
        session=session,
        controller_id="cid",
        product="network",
        attr_name="client_manager",
        site="default",
    )
    domain_manager.get_clients.assert_awaited_once_with(include_offline=False)
    factory.get_connection_manager.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_read_action_reaches_manager_without_confirm() -> None:
    entry = ToolEntry(
        name="protect_list_cameras",
        product="protect",
        category="cameras",
        manager="",
        method="",
        permission_action="read",
        read_only_hint=True,
    )
    expected = {"success": True, "data": []}
    manager = MagicMock()
    manager.get_cameras = AsyncMock(return_value=expected)
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)

    result = await dispatch_action(
        registry=_registry_with(entry),
        factory=factory,
        session=MagicMock(),
        tool_name=entry.name,
        controller_id="cid",
        controller_products=[entry.product],
        site="default",
        args={"include_stats": False},
        confirm=False,
        dispatch_table={
            entry.name: DispatchEntry(manager_attr="camera_manager", method="get_cameras"),
        },
    )

    assert result is expected
    manager.get_cameras.assert_awaited_once_with(include_stats=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("permission_action", ["create", "update", "delete"])
async def test_confirmed_mutation_actions_reach_manager_unchanged(permission_action: str) -> None:
    tool_name = f"access_{permission_action}_test_resource"
    entry = ToolEntry(
        name=tool_name,
        product="access",
        category="test",
        manager="",
        method="",
        permission_action=permission_action,
        read_only_hint=False,
    )
    expected = {"success": True, "action": permission_action}
    manager = MagicMock()
    manager.apply_action = AsyncMock(return_value=expected)
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)
    args = {"resource_id": "resource-1", "enabled": True}

    result = await dispatch_action(
        registry=_registry_with(entry),
        factory=factory,
        session=MagicMock(),
        tool_name=tool_name,
        controller_id="cid",
        controller_products=[entry.product],
        site="default",
        args=args,
        confirm=True,
        dispatch_table={
            tool_name: DispatchEntry(manager_attr="test_manager", method="apply_action"),
        },
    )

    assert result is expected
    manager.apply_action.assert_awaited_once_with(**args)


@pytest.mark.asyncio
@pytest.mark.parametrize("manager_result", [None, False])
async def test_confirmed_mutation_rejects_bare_manager_failure(manager_result: object) -> None:
    entry = ToolEntry(
        name="access_update_test_resource",
        product="access",
        category="test",
        manager="test_manager",
        method="apply_action",
        permission_action="update",
        read_only_hint=False,
    )
    manager = MagicMock()
    manager.apply_action = AsyncMock(return_value=manager_result)
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)

    with pytest.raises(ValueError, match="reported failure"):
        await dispatch_action(
            registry=ManifestRegistry({entry.name: entry}),
            factory=factory,
            session=MagicMock(),
            tool_name=entry.name,
            controller_id="cid",
            controller_products=[entry.product],
            site="default",
            args={},
            confirm=True,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("permission_action", "read_only_hint"),
    [
        ("", None),
        ("archive", False),
        ("read", False),
        ("update", True),
    ],
)
async def test_ambiguous_or_conflicting_safety_metadata_fails_closed(
    permission_action: str,
    read_only_hint: bool | None,
) -> None:
    entry = ToolEntry(
        name="access_test_action",
        product="access",
        category="test",
        manager="",
        method="",
        permission_action=permission_action,
        read_only_hint=read_only_hint,
    )
    factory = MagicMock()

    with pytest.raises(ValueError, match="invalid safety metadata"):
        await dispatch_action(
            registry=_registry_with(entry),
            factory=factory,
            session=MagicMock(),
            tool_name=entry.name,
            controller_id="cid",
            controller_products=[entry.product],
            site="default",
            args={},
            confirm=False,
            dispatch_table={},
        )

    factory.get_domain_manager.assert_not_called()


@pytest.mark.asyncio
async def test_capability_mismatch_precedes_safety_metadata_validation() -> None:
    entry = ToolEntry(
        name="access_test_action",
        product="access",
        category="test",
        manager="",
        method="",
        permission_action="",
        read_only_hint=None,
    )
    factory = MagicMock()

    with pytest.raises(CapabilityMismatch):
        await dispatch_action(
            registry=_registry_with(entry),
            factory=factory,
            session=MagicMock(),
            tool_name=entry.name,
            controller_id="cid",
            controller_products=["network"],
            site="default",
            args={},
            confirm=False,
            dispatch_table={},
        )

    factory.get_domain_manager.assert_not_called()


@pytest.mark.asyncio
async def test_preview_argument_validation_precedes_preview_response() -> None:
    entry = ToolEntry(
        name="access_update_test_resource",
        product="access",
        category="test",
        manager="test_manager",
        method="update_test_resource",
        permission_action="update",
        read_only_hint=False,
    )
    factory = MagicMock()

    with pytest.raises(ValueError, match="include_sensitive is not supported"):
        await dispatch_action(
            registry=_registry_with(entry),
            factory=factory,
            session=MagicMock(),
            tool_name=entry.name,
            controller_id="cid",
            controller_products=[entry.product],
            site="default",
            args={"include_sensitive": True},
            confirm=False,
        )

    factory.get_domain_manager.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_rejects_include_sensitive_arg_before_manager_invocation() -> None:
    entry = ToolEntry(
        name="unifi_get_wlan_details",
        product="network",
        category="networks",
        manager="",
        method="",
    )
    registry = _registry_with(entry)

    domain_manager = MagicMock()
    domain_manager.get_wlan_details = AsyncMock(return_value={"_id": "w1", "name": "SSID"})

    conn_manager = MagicMock()
    conn_manager.site = "default"
    conn_manager.set_site = AsyncMock()

    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=domain_manager)
    factory.get_connection_manager = AsyncMock(return_value=conn_manager)

    with pytest.raises(ValueError, match="include_sensitive is not supported"):
        await dispatch_action(
            registry=registry,
            factory=factory,
            session=MagicMock(),
            tool_name="unifi_get_wlan_details",
            controller_id="cid",
            controller_products=["network"],
            site="default",
            args={"wlan_id": "w1", "include_sensitive": True},
            confirm=False,
            dispatch_table={
                "unifi_get_wlan_details": DispatchEntry(manager_attr="network_manager", method="get_wlan_details"),
            },
        )

    factory.get_domain_manager.assert_not_awaited()
    domain_manager.get_wlan_details.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_scopes_manager_to_requested_site_without_mutating_connection() -> None:
    entry = ToolEntry(
        name="unifi_list_clients",
        product="network",
        category="clients",
        manager="",
        method="",
    )
    registry = _registry_with(entry)

    domain_manager = MagicMock()
    domain_manager.get_clients = AsyncMock(return_value=[])

    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=domain_manager)
    factory.get_connection_manager = AsyncMock()
    session = MagicMock()

    await dispatch_action(
        registry=registry,
        factory=factory,
        session=session,
        tool_name="unifi_list_clients",
        controller_id="cid",
        controller_products=["network"],
        site="upstairs",
        args={},
        confirm=False,
        dispatch_table={
            "unifi_list_clients": DispatchEntry(manager_attr="client_manager", method="get_clients"),
        },
    )

    factory.get_domain_manager.assert_awaited_once_with(
        session=session,
        controller_id="cid",
        product="network",
        attr_name="client_manager",
        site="upstairs",
    )
    factory.get_connection_manager.assert_not_awaited()
    domain_manager.get_clients.assert_awaited_once_with(include_offline=False)


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
    recognition_entry = table.get("protect_list_known_faces")
    assert recognition_entry is not None
    assert recognition_entry.manager_attr == "recognition_manager"
    assert recognition_entry.method == "list_known_faces"

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
        assert entry.method == method, f"{tool_name} method: got {entry.method!r}, want {method!r}"


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
    assert table["unifi_reorder_firewall_policies"].method == "reorder_firewall_policies"
    # update_traffic_route pre-fetches the route for its preview, so the AST captures
    # get_traffic_route_details; the override must pin it to the mutation method.
    assert table["unifi_update_traffic_route"].manager_attr == "traffic_route_manager"
    assert table["unifi_update_traffic_route"].method == "update_traffic_route"
    # Stats: list-returning method (was AST-captured as get_X_details, a dict)
    assert table["unifi_get_device_stats"].manager_attr == "stats_manager"
    assert table["unifi_get_device_stats"].method == "get_device_stats_for_identifier"
    assert table["unifi_get_client_stats"].method == "get_client_stats_for_identifier"

    # Protect preview/execute split
    assert table["protect_reboot_camera"].method == "apply_reboot_camera"
    assert table["protect_alarm_arm"].method == "arm"
    assert table["protect_acknowledge_event"].method == "apply_acknowledge_event"
    assert table["protect_update_sensor_settings"].manager_attr == "sensor_manager"
    assert table["protect_update_sensor_settings"].method == "apply_sensor_settings"
    assert table["protect_update_chime"].manager_attr == "chime_manager"
    assert table["protect_update_chime"].method == "apply_chime_settings"
    assert table["protect_update_viewer"].manager_attr == "system_manager"
    assert table["protect_update_viewer"].method == "apply_viewer_update"
    assert table["protect_update_known_face"].method == "apply_update_known_face"
    assert table["protect_merge_known_faces"].method == "apply_merge_known_faces"
    assert table["protect_delete_known_face"].method == "apply_delete_known_face"
    # Alarm rule mutations use the facade so v2 UUIDs and legacy ObjectIDs share
    # the same API action path as the MCP tools.
    assert table["protect_alarm_update_rule"].manager_attr == "alarm_facade"
    assert table["protect_alarm_update_rule"].method == "update_rule"
    assert table["protect_alarm_delete_rule"].manager_attr == "alarm_facade"
    assert table["protect_alarm_delete_rule"].method == "delete_rule"
    # create_rule's only await is the facade mutation itself — AST is correct, no override.
    assert table["protect_alarm_create_rule"].manager_attr == "alarm_facade"
    assert table["protect_alarm_create_rule"].method == "create_rule"

    # Access preview/execute split
    assert table["access_lock_door"].method == "apply_lock_door"
    assert table["access_create_credential"].method == "apply_create_credential"
    assert table["access_update_policy"].method == "apply_update_policy"


@pytest.mark.asyncio
async def test_dispatch_update_traffic_route_routes_to_mutation_with_widened_field() -> None:
    """Regression: unifi_update_traffic_route pre-fetches the route via
    get_traffic_route_details to render a current-vs-proposed preview, so the AST
    dispatcher captures the READ method first. The DISPATCH_OVERRIDES entry must
    redirect dispatch to the mutation method, and a widened match field
    (target_devices) must reach the manager.

    Uses the REAL build_dispatch_table() so this exercises the override wiring, not
    just dispatch_action's arg forwarding.
    """
    entry = ToolEntry(
        name="unifi_update_traffic_route",
        product="network",
        category="traffic_routes",
        manager="",
        method="",
    )
    registry = _registry_with(entry)

    domain_manager = MagicMock()
    domain_manager.update_traffic_route = AsyncMock(return_value=True)

    conn_manager = MagicMock()
    conn_manager.site = "default"
    conn_manager.set_site = AsyncMock()

    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=domain_manager)
    factory.get_connection_manager = AsyncMock(return_value=conn_manager)

    session = MagicMock()
    target_devices = [{"type": "CLIENT", "client_mac": "aa:bb:cc:dd:ee:ff"}]
    await dispatch_action(
        registry=registry,
        factory=factory,
        session=session,
        tool_name="unifi_update_traffic_route",
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args={"route_id": "tr1", "target_devices": target_devices},
        confirm=True,
        dispatch_table=build_dispatch_table(),
    )

    # Override resolved to the traffic_route_manager mutation, NOT the read method
    # get_traffic_route_details the AST would otherwise capture.
    factory.get_domain_manager.assert_awaited_once_with(
        session=session,
        controller_id="cid",
        product="network",
        attr_name="traffic_route_manager",
        site="default",
    )
    # The widened match field is forwarded to update_traffic_route as a kwarg
    # (no arg translator — the manager takes **kwargs; confirm is a separate arg).
    domain_manager.update_traffic_route.assert_awaited_once_with(route_id="tr1", target_devices=target_devices)


@pytest.mark.asyncio
async def test_dispatch_protect_update_sensor_settings_translates_settings_to_public_payload() -> None:
    entry = ToolEntry(
        name="protect_update_sensor_settings",
        product="protect",
        category="devices",
        manager="",
        method="",
    )
    registry = _registry_with(entry)

    domain_manager = MagicMock()
    domain_manager.update_sensor_settings = AsyncMock(return_value={"preview": True})
    domain_manager.apply_sensor_settings = AsyncMock(return_value={"sensor_id": "sensor-1"})

    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=domain_manager)

    await dispatch_action(
        registry=registry,
        factory=factory,
        session=MagicMock(),
        tool_name="protect_update_sensor_settings",
        controller_id="cid",
        controller_products=["protect"],
        site="default",
        args={
            "sensor_id": "sensor-1",
            "settings": {
                "name": "Garage",
                "motion_settings": {"sensitivity_when_armed": 80},
            },
        },
        confirm=True,
        dispatch_table=build_dispatch_table(),
    )

    domain_manager.update_sensor_settings.assert_not_awaited()
    domain_manager.apply_sensor_settings.assert_awaited_once_with(
        "sensor-1",
        {
            "name": "Garage",
            "motion_settings": {"sensitivityWhenArmed": 80},
        },
    )


@pytest.mark.asyncio
async def test_dispatch_protect_update_chime_passes_global_settings() -> None:
    entry = ToolEntry(
        name="protect_update_chime",
        product="protect",
        category="devices",
        manager="",
        method="",
    )
    registry = _registry_with(entry)

    domain_manager = MagicMock()
    domain_manager.apply_chime_settings = AsyncMock(return_value={"chime_id": "chime-1"})

    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=domain_manager)

    await dispatch_action(
        registry=registry,
        factory=factory,
        session=MagicMock(),
        tool_name="protect_update_chime",
        controller_id="cid",
        controller_products=["protect"],
        site="default",
        args={"chime_id": "chime-1", "settings": {"volume": 75}},
        confirm=True,
        dispatch_table=build_dispatch_table(),
    )

    domain_manager.apply_chime_settings.assert_awaited_once_with("chime-1", {"volume": 75})


@pytest.mark.asyncio
async def test_dispatch_protect_update_chime_preserves_per_camera_ring_settings() -> None:
    entry = ToolEntry(
        name="protect_update_chime",
        product="protect",
        category="devices",
        manager="",
        method="",
    )
    registry = _registry_with(entry)

    domain_manager = MagicMock()
    domain_manager.apply_chime_settings = AsyncMock(return_value={"chime_id": "chime-1"})

    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=domain_manager)

    await dispatch_action(
        registry=registry,
        factory=factory,
        session=MagicMock(),
        tool_name="protect_update_chime",
        controller_id="cid",
        controller_products=["protect"],
        site="default",
        args={"chime_id": "chime-1", "settings": {"camera_id": "cam-1", "repeat_times": 3}},
        confirm=True,
        dispatch_table=build_dispatch_table(),
    )

    domain_manager.apply_chime_settings.assert_awaited_once_with(
        "chime-1",
        {"camera_id": "cam-1", "repeat_times": 3},
    )


@pytest.mark.asyncio
async def test_dispatch_protect_update_chime_rejects_unsupported_only_settings() -> None:
    entry = ToolEntry(
        name="protect_update_chime",
        product="protect",
        category="devices",
        manager="",
        method="",
    )
    registry = _registry_with(entry)

    domain_manager = MagicMock()
    domain_manager.apply_chime_settings = AsyncMock(return_value={"chime_id": "chime-1"})

    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=domain_manager)

    with pytest.raises(ValueError, match="Unsupported chime setting fields"):
        await dispatch_action(
            registry=registry,
            factory=factory,
            session=MagicMock(),
            tool_name="protect_update_chime",
            controller_id="cid",
            controller_products=["protect"],
            site="default",
            args={"chime_id": "chime-1", "settings": {"unsupported": True}},
            confirm=True,
            dispatch_table=build_dispatch_table(),
        )

    domain_manager.apply_chime_settings.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_protect_update_chime_rejects_mixed_unsupported_global_settings() -> None:
    entry = ToolEntry(
        name="protect_update_chime",
        product="protect",
        category="devices",
        manager="",
        method="",
    )
    registry = _registry_with(entry)

    domain_manager = MagicMock()
    domain_manager.apply_chime_settings = AsyncMock(return_value={"chime_id": "chime-1"})

    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=domain_manager)

    with pytest.raises(ValueError, match="Unsupported chime setting fields"):
        await dispatch_action(
            registry=registry,
            factory=factory,
            session=MagicMock(),
            tool_name="protect_update_chime",
            controller_id="cid",
            controller_products=["protect"],
            site="default",
            args={"chime_id": "chime-1", "settings": {"volume": 75, "volumee": 20}},
            confirm=True,
            dispatch_table=build_dispatch_table(),
        )

    domain_manager.apply_chime_settings.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_protect_update_viewer_routes_to_apply_viewer_update() -> None:
    entry = ToolEntry(
        name="protect_update_viewer",
        product="protect",
        category="system",
        manager="",
        method="",
    )
    registry = _registry_with(entry)

    domain_manager = MagicMock()
    domain_manager.update_viewer = AsyncMock(return_value={"preview": True})
    domain_manager.apply_viewer_update = AsyncMock(return_value={"viewer_id": "viewer-1"})

    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=domain_manager)

    await dispatch_action(
        registry=registry,
        factory=factory,
        session=MagicMock(),
        tool_name="protect_update_viewer",
        controller_id="cid",
        controller_products=["protect"],
        site="default",
        args={"viewer_id": "viewer-1", "settings": {"liveview_id": "liveview-1"}},
        confirm=True,
        dispatch_table=build_dispatch_table(),
    )

    domain_manager.update_viewer.assert_not_awaited()
    domain_manager.apply_viewer_update.assert_awaited_once_with(
        viewer_id="viewer-1",
        settings={"liveview_id": "liveview-1"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "product", "args"),
    [
        ("unifi_delete_dns_record", "network", {"dns_record_id": "dns-1"}),
        ("protect_alarm_delete_rule", "protect", {"rule_id": "rule-1"}),
        ("access_delete_visitor", "access", {"visitor_id": "visitor-1"}),
    ],
)
async def test_dispatch_delete_actions_return_preview_without_manager(
    tool_name: str,
    product: str,
    args: dict,
) -> None:
    entry = ToolEntry(
        name=tool_name,
        product=product,
        category="test",
        manager="test_manager",
        method="delete_resource",
        permission_action="delete",
        read_only_hint=False,
    )
    registry = _registry_with(entry)
    factory = MagicMock()

    result = await dispatch_action(
        registry=registry,
        factory=factory,
        session=MagicMock(),
        tool_name=tool_name,
        controller_id="cid",
        controller_products=[product],
        site="default",
        args=args,
        confirm=False,
    )

    assert isinstance(result, MutationPreview)
    assert result.payload["action"] == "delete"
    assert result.payload["tool"] == tool_name
    factory.get_domain_manager.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_access_create_visitor_preserves_developer_fields() -> None:
    entry = ToolEntry(
        name="access_create_visitor",
        product="access",
        category="visitor",
        manager="",
        method="",
        permission_action="create",
        read_only_hint=False,
    )
    registry = _registry_with(entry)
    manager = MagicMock()
    manager.apply_create_visitor = AsyncMock(
        return_value={"action": "create", "result": "success", "data": {"id": "visitor-uuid"}}
    )
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)
    args = {
        "name": "Smoke Visitor",
        "valid_from": "2026-03-17T09:00:00Z",
        "valid_until": "2026-03-17T17:00:00Z",
        "first_name": "Smoke",
        "last_name": "Visitor",
        "company": "Example Co",
    }

    result = await dispatch_action(
        registry=registry,
        factory=factory,
        session=MagicMock(),
        tool_name="access_create_visitor",
        controller_id="cid",
        controller_products=["access"],
        site="default",
        args=args,
        confirm=True,
        dispatch_table={
            "access_create_visitor": DispatchEntry(
                manager_attr="visitor_manager",
                method="apply_create_visitor",
            )
        },
    )

    assert result["data"]["id"] == "visitor-uuid"
    manager.apply_create_visitor.assert_awaited_once_with(**args)


@pytest.mark.asyncio
async def test_dispatch_confirmed_delete_reaches_manager() -> None:
    entry = ToolEntry(
        name="access_delete_visitor",
        product="access",
        category="visitor",
        manager="",
        method="",
        permission_action="delete",
        read_only_hint=False,
    )
    registry = _registry_with(entry)
    manager = MagicMock()
    manager.apply_delete_visitor = AsyncMock(return_value={"visitor_id": "visitor-1", "result": "success"})
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)

    result = await dispatch_action(
        registry=registry,
        factory=factory,
        session=MagicMock(),
        tool_name="access_delete_visitor",
        controller_id="cid",
        controller_products=["access"],
        site="default",
        args={"visitor_id": "visitor-1"},
        confirm=True,
        dispatch_table={
            "access_delete_visitor": DispatchEntry(
                manager_attr="visitor_manager",
                method="apply_delete_visitor",
            )
        },
    )

    assert result == {"visitor_id": "visitor-1", "result": "success"}
    manager.apply_delete_visitor.assert_awaited_once_with(visitor_id="visitor-1")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "args"),
    [
        ("protect_update_sensor_settings", {"sensor_id": "sensor-1", "settings": {"name": "Garage"}}),
        ("protect_update_chime", {"chime_id": "chime-1", "settings": {"volume": 75}}),
        ("protect_update_viewer", {"viewer_id": "viewer-1", "settings": {"name": "Lobby"}}),
    ],
)
async def test_dispatch_protect_capability_actions_return_preview(tool_name: str, args: dict) -> None:
    entry = ToolEntry(
        name=tool_name,
        product="protect",
        category="devices",
        manager="",
        method="",
        permission_action="update",
        read_only_hint=False,
    )
    registry = _registry_with(entry)
    factory = MagicMock()

    result = await dispatch_action(
        registry=registry,
        factory=factory,
        session=MagicMock(),
        tool_name=tool_name,
        controller_id="cid",
        controller_products=["protect"],
        site="default",
        args=args,
        confirm=False,
        dispatch_table=build_dispatch_table(),
    )

    assert isinstance(result, MutationPreview)
    assert result.payload["product"] == "protect"
    assert result.payload["preview"]["proposed"] == args
    factory.get_domain_manager.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_reorder_firewall_policies_returns_preview() -> None:
    entry = ToolEntry(
        name="unifi_reorder_firewall_policies",
        product="network",
        category="firewall",
        manager="",
        method="",
        permission_action="update",
        read_only_hint=False,
    )
    registry = _registry_with(entry)
    factory = MagicMock()

    args = {
        "source_firewall_zone_id": "zone-src",
        "destination_firewall_zone_id": "zone-dst",
        "ordered_firewall_policy_ids": {
            "beforeSystemDefined": ["allow-1"],
            "afterSystemDefined": ["block-1"],
        },
    }
    result = await dispatch_action(
        registry=registry,
        factory=factory,
        session=MagicMock(),
        tool_name="unifi_reorder_firewall_policies",
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args=args,
        confirm=False,
        dispatch_table={
            "unifi_reorder_firewall_policies": DispatchEntry(
                manager_attr="firewall_manager",
                method="reorder_firewall_policies",
            ),
        },
    )

    assert isinstance(result, MutationPreview)
    assert result.payload["preview"]["proposed"] == args
    assert result.payload["resource_id"] == "zone-src"
    factory.get_domain_manager.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_update_wlan_rejects_redaction_marker_before_manager() -> None:
    entry = ToolEntry(
        name="unifi_update_wlan",
        product="network",
        category="networks",
        manager="",
        method="",
    )
    registry = _registry_with(entry)
    factory = MagicMock()

    with pytest.raises(ValueError, match="omit update_data.x_passphrase"):
        await dispatch_action(
            registry=registry,
            factory=factory,
            session=MagicMock(),
            tool_name="unifi_update_wlan",
            controller_id="cid",
            controller_products=["network"],
            site="default",
            args={"wlan_id": "w1", "update_data": {"x_passphrase": REDACTED}},
            confirm=True,
            dispatch_table={
                "unifi_update_wlan": DispatchEntry(manager_attr="network_manager", method="update_wlan"),
            },
        )

    factory.get_domain_manager.assert_not_called()


# -----------------------------------------------------------------------------
# Argument translators — bridge tool flat kwargs → manager-shaped positional args
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_translates_acl_create_kwargs_to_controller_payload() -> None:
    """unifi_create_acl_rule: the MCP tool accepts flat kwargs and builds a
    controller-shaped payload before calling AclManager.create_acl_rule(payload).
    The action dispatcher must apply the same translation."""
    entry = ToolEntry(
        name="unifi_create_acl_rule",
        product="network",
        category="acl_rules",
        manager="",
        method="",
    )
    registry = _registry_with(entry)

    domain_manager = MagicMock()
    domain_manager.create_acl_rule = AsyncMock(return_value={"_id": "r1"})

    conn_manager = MagicMock()
    conn_manager.site = "default"
    conn_manager.set_site = AsyncMock()

    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=domain_manager)
    factory.get_connection_manager = AsyncMock(return_value=conn_manager)

    result = await dispatch_action(
        registry=registry,
        factory=factory,
        session=MagicMock(),
        tool_name="unifi_create_acl_rule",
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args={
            "name": "Block guest IoT",
            "acl_index": 65000,
            "action": "block",  # lowercase — tool layer uppercases
            "network_id": "net001",
            "source_macs": ["aa:bb:cc:dd:ee:ff"],
            "destination_macs": ["01:00:5e:00:00:00"],
            "destination_netmask": 24,  # must survive the API translation boundary
            "enabled": True,
        },
        confirm=True,
        dispatch_table={
            "unifi_create_acl_rule": DispatchEntry(manager_attr="acl_manager", method="create_acl_rule"),
        },
    )

    assert result == {"_id": "r1"}
    # Manager called with exactly one positional dict containing controller-shape
    domain_manager.create_acl_rule.assert_awaited_once()
    (positional, keyword) = domain_manager.create_acl_rule.await_args
    assert keyword == {}, f"expected no kwargs; got {keyword}"
    assert len(positional) == 1, f"expected one positional arg; got {positional}"
    payload = positional[0]
    assert payload["name"] == "Block guest IoT"
    assert payload["acl_index"] == 65000
    assert payload["action"] == "BLOCK"  # uppercased
    assert payload["mac_acl_network_id"] == "net001"
    assert payload["traffic_source"]["specific_mac_addresses"] == ["aa:bb:cc:dd:ee:ff"]
    assert payload["traffic_source"]["type"] == "CLIENT_MAC"
    assert payload["traffic_destination"]["specific_mac_addresses"] == ["01:00:5e:00:00:00"]
    # netmask passed through the API dispatch translator and converted to a bitmask
    assert payload["traffic_destination"]["mac_mask"] == "ff:ff:ff:00:00:00"


@pytest.mark.asyncio
async def test_dispatch_translates_acl_update_kwargs_to_rule_id_plus_payload() -> None:
    """unifi_update_acl_rule: the tool accepts (rule_id, **fields) and calls
    AclManager.update_acl_rule(rule_id, controller_update_payload). The action
    dispatcher must perform the same translation."""
    entry = ToolEntry(
        name="unifi_update_acl_rule",
        product="network",
        category="acl_rules",
        manager="",
        method="",
    )
    registry = _registry_with(entry)

    domain_manager = MagicMock()
    domain_manager.update_acl_rule = AsyncMock(return_value={"_id": "r1", "name": "New"})

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
        tool_name="unifi_update_acl_rule",
        controller_id="cid",
        controller_products=["network"],
        site="default",
        # fields are nested in rule_data (the real tool/manifest schema), NOT top-level
        args={
            "rule_id": "r1",
            "rule_data": {"name": "New", "source_macs": ["11:22:33:44:55:66"]},
        },
        confirm=True,
        dispatch_table={
            "unifi_update_acl_rule": DispatchEntry(manager_attr="acl_manager", method="update_acl_rule"),
        },
    )

    domain_manager.update_acl_rule.assert_awaited_once()
    (positional, keyword) = domain_manager.update_acl_rule.await_args
    assert keyword == {}, f"expected no kwargs; got {keyword}"
    assert positional[0] == "r1"
    update_payload = positional[1]
    assert update_payload["name"] == "New"
    assert update_payload["traffic_source"]["specific_mac_addresses"] == ["11:22:33:44:55:66"]
    # Field not provided in args is absent from the controller update payload
    assert "traffic_destination" not in update_payload
    assert "acl_index" not in update_payload


@pytest.mark.asyncio
async def test_dispatch_translates_gateway_settings_update_filters_to_mutable() -> None:
    """unifi_update_gateway_settings: the action dispatcher must filter update_data
    to mutable keys (dropping read-only / unknown) and pass it as the single
    positional arg to GatewaySettingsManager.update_gateway_settings — the manager
    itself does not filter, so this is the only guard on the /v1/actions path."""
    entry = ToolEntry(
        name="unifi_update_gateway_settings",
        product="network",
        category="gateway_settings",
        manager="",
        method="",
    )
    registry = _registry_with(entry)

    domain_manager = MagicMock()
    domain_manager.update_gateway_settings = AsyncMock(return_value=(True, None))

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
        tool_name="unifi_update_gateway_settings",
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args={
            "update_data": {
                "upnp_enabled": True,
                "echo_server": "1.1.1.1",
                "_id": "x",
                "key": "usg",
                "bogus": 1,
            }
        },
        confirm=True,
        dispatch_table={
            "unifi_update_gateway_settings": DispatchEntry(
                manager_attr="gateway_settings_manager", method="update_gateway_settings"
            ),
        },
    )

    domain_manager.update_gateway_settings.assert_awaited_once()
    (positional, keyword) = domain_manager.update_gateway_settings.await_args
    assert keyword == {}, f"expected no kwargs; got {keyword}"
    # read-only (_id, key) + unknown (bogus) filtered out; only the mutable field survives
    assert positional[0] == {"upnp_enabled": True, "echo_server": "1.1.1.1"}


def test_update_network_translator_forwards_firewall_zone_and_wan_monitor_fields() -> None:
    translator = DISPATCH_ARG_TRANSLATORS["unifi_update_network"]
    fields = {
        "firewall_zone_id": "zone-v2-1",
        "wan_sla": "sla-1",
        "report_wan_event": False,
    }

    _, kwargs = translator({"network_id": "wan-1", "update_data": fields})

    assert kwargs == {"network_id": "wan-1", "update_data": fields}


@pytest.mark.parametrize(
    ("tool_name", "args", "expected_kwargs"),
    [
        ("unifi_create_firewall_zone", {"name": "IoT", "confirm": True}, {"name": "IoT"}),
        (
            "unifi_update_firewall_zone",
            {"zone_id": "v2-zone", "name": "Devices", "confirm": True},
            {"zone_id": "v2-zone", "name": "Devices"},
        ),
        ("unifi_delete_firewall_zone", {"zone_id": "v2-zone", "confirm": True}, {"zone_id": "v2-zone"}),
    ],
)
def test_firewall_zone_crud_translators_drop_confirmation(
    tool_name: str,
    args: dict[str, object],
    expected_kwargs: dict[str, object],
) -> None:
    positional, kwargs = DISPATCH_ARG_TRANSLATORS[tool_name](args)

    assert positional == ()
    assert kwargs == expected_kwargs


@pytest.mark.parametrize(
    ("tool_name", "args", "expected_kwargs"),
    [
        ("unifi_create_firewall_zone", {"name": "  IoT  "}, {"name": "IoT"}),
        (
            "unifi_update_firewall_zone",
            {"zone_id": "  v2-zone  ", "name": "  Devices  "},
            {"zone_id": "v2-zone", "name": "Devices"},
        ),
        ("unifi_delete_firewall_zone", {"zone_id": "  v2-zone  "}, {"zone_id": "v2-zone"}),
    ],
)
def test_firewall_zone_crud_translators_trim_strings(
    tool_name: str,
    args: dict[str, object],
    expected_kwargs: dict[str, object],
) -> None:
    _, kwargs = DISPATCH_ARG_TRANSLATORS[tool_name](args)

    assert kwargs == expected_kwargs


@pytest.mark.parametrize(
    ("tool_name", "args", "field"),
    [
        ("unifi_create_firewall_zone", {"name": "   "}, "name"),
        ("unifi_update_firewall_zone", {"zone_id": "z1", "name": "   "}, "name"),
        ("unifi_delete_firewall_zone", {"zone_id": "   "}, "zone_id"),
    ],
)
def test_firewall_zone_crud_translators_reject_blank_strings(
    tool_name: str,
    args: dict[str, object],
    field: str,
) -> None:
    with pytest.raises(ValueError, match=rf"^{field} is required$"):
        DISPATCH_ARG_TRANSLATORS[tool_name](args)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "args", "method_name", "expected_args"),
    [
        (
            "unifi_update_firewall_zone",
            {"zone_id": "v2-zone", "name": "Devices"},
            "update_firewall_zone",
            ("v2-zone", "Devices"),
        ),
        (
            "unifi_delete_firewall_zone",
            {"zone_id": "v2-zone"},
            "delete_firewall_zone",
            ("v2-zone",),
        ),
    ],
)
async def test_dispatch_real_table_binds_firewall_zone_preview_tools_to_mutations(
    tool_name: str,
    args: dict[str, object],
    method_name: str,
    expected_args: tuple[object, ...],
) -> None:
    entry = ToolEntry(name=tool_name, product="network", category="firewall", manager="", method="")
    registry = _registry_with(entry)
    domain_manager = MagicMock()
    setattr(domain_manager, method_name, AsyncMock(return_value=True))
    domain_manager.get_firewall_zone_by_id = AsyncMock(return_value={"_id": "v2-zone", "name": "IoT"})
    conn_manager = MagicMock(site="default")
    conn_manager.set_site = AsyncMock()
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=domain_manager)
    factory.get_connection_manager = AsyncMock(return_value=conn_manager)

    await dispatch_action(
        registry=registry,
        factory=factory,
        session=MagicMock(),
        tool_name=tool_name,
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args=args,
        confirm=True,
        dispatch_table=build_dispatch_table(),
    )

    expected_kwargs = dict(zip(args, expected_args, strict=True))
    getattr(domain_manager, method_name).assert_awaited_once_with(**expected_kwargs)
    domain_manager.get_firewall_zone_by_id.assert_not_awaited()


def _ddns_factory():
    domain_manager = MagicMock()
    domain_manager.update_dynamic_dns = AsyncMock(return_value={"_id": "ddns001"})
    domain_manager.create_dynamic_dns = AsyncMock(return_value={"_id": "ddns_new"})
    # get_dynamic_dns is the READ the update tool now pre-fetches for its preview;
    # stub it so a wrong AST binding fails as a clean assertion, not a TypeError.
    domain_manager.get_dynamic_dns = AsyncMock(return_value={"_id": "ddns001", "host_name": "old.example.com"})
    conn_manager = MagicMock(site="default")
    conn_manager.set_site = AsyncMock()
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=domain_manager)
    factory.get_connection_manager = AsyncMock(return_value=conn_manager)
    return factory, domain_manager


@pytest.mark.asyncio
async def test_dispatch_real_table_binds_dynamic_dns_update_to_mutation() -> None:
    """Regression: update_dynamic_dns pre-fetches the current entry via
    get_dynamic_dns to render a real current-vs-proposed preview, so the AST
    dispatcher captures the READ method first. A DISPATCH_OVERRIDES entry must
    redirect dispatch to the mutation method (update_dynamic_dns).

    Uses the REAL build_dispatch_table() — the hand-built dispatch_table the other
    DDNS tests use would hide a wrong method binding (which the AST would pick)."""
    entry = ToolEntry(name="unifi_update_dynamic_dns", product="network", category="dynamic_dns", manager="", method="")
    registry = _registry_with(entry)
    factory, domain_manager = _ddns_factory()

    await dispatch_action(
        registry=registry,
        factory=factory,
        session=MagicMock(),
        tool_name="unifi_update_dynamic_dns",
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args={"entry_id": "ddns001", "update_data": {"host_name": "new.example.com"}},
        confirm=True,
        dispatch_table=build_dispatch_table(),
    )

    # Bound to the mutation, NOT the get_dynamic_dns read the AST captures first.
    domain_manager.update_dynamic_dns.assert_awaited_once_with("ddns001", {"host_name": "new.example.com"})
    domain_manager.get_dynamic_dns.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_real_table_binds_dynamic_dns_create_to_mutation() -> None:
    """The create tool has no pre-fetch, so the AST binds it correctly — pin it in
    the real table too, guarding against a future preview refactor."""
    entry = ToolEntry(name="unifi_create_dynamic_dns", product="network", category="dynamic_dns", manager="", method="")
    registry = _registry_with(entry)
    factory, domain_manager = _ddns_factory()

    await dispatch_action(
        registry=registry,
        factory=factory,
        session=MagicMock(),
        tool_name="unifi_create_dynamic_dns",
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args={"entry_data": {"host_name": "home.example.com", "service": "dyndns"}},
        confirm=True,
        dispatch_table=build_dispatch_table(),
    )

    domain_manager.create_dynamic_dns.assert_awaited_once_with({"host_name": "home.example.com", "service": "dyndns"})


@pytest.mark.asyncio
async def test_dispatch_translates_dynamic_dns_update_to_entry_id_plus_payload() -> None:
    """unifi_update_dynamic_dns: the tool exposes ``update_data`` but the manager
    method is ``update_dynamic_dns(entry_id, entry_data)``. The translator must
    rename/reshape to positional ``(entry_id, filtered_payload)`` — without it the
    /v1/actions path calls the manager with an unexpected ``update_data=`` kwarg."""
    entry = ToolEntry(name="unifi_update_dynamic_dns", product="network", category="dynamic_dns", manager="", method="")
    registry = _registry_with(entry)
    factory, domain_manager = _ddns_factory()

    await dispatch_action(
        registry=registry,
        factory=factory,
        session=MagicMock(),
        tool_name="unifi_update_dynamic_dns",
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args={"entry_id": "ddns001", "update_data": {"service": "noip", "interface": "wan2"}},
        confirm=True,
        dispatch_table={
            "unifi_update_dynamic_dns": DispatchEntry(manager_attr="dynamic_dns_manager", method="update_dynamic_dns")
        },
    )

    domain_manager.update_dynamic_dns.assert_awaited_once()
    (positional, keyword) = domain_manager.update_dynamic_dns.await_args
    assert keyword == {}, f"expected no kwargs; got {keyword}"
    assert positional == ("ddns001", {"service": "noip", "interface": "wan2"})


@pytest.mark.asyncio
async def test_dispatch_dynamic_dns_update_rejects_unknown_field() -> None:
    """Unknown keys in update_data must fail with an actionable error, not be
    silently forwarded/dropped on the /v1/actions path."""
    entry = ToolEntry(name="unifi_update_dynamic_dns", product="network", category="dynamic_dns", manager="", method="")
    registry = _registry_with(entry)
    factory, domain_manager = _ddns_factory()

    with pytest.raises(ValueError, match="Unknown or read-only fields"):
        await dispatch_action(
            registry=registry,
            factory=factory,
            session=MagicMock(),
            tool_name="unifi_update_dynamic_dns",
            controller_id="cid",
            controller_products=["network"],
            site="default",
            args={"entry_id": "ddns001", "update_data": {"bogus_field": "x"}},
            confirm=True,
            dispatch_table={
                "unifi_update_dynamic_dns": DispatchEntry(
                    manager_attr="dynamic_dns_manager", method="update_dynamic_dns"
                )
            },
        )
    domain_manager.update_dynamic_dns.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_dynamic_dns_update_rejects_read_only_field() -> None:
    """Read-only keys (id/site_id) in update_data must fail, not be dropped."""
    entry = ToolEntry(name="unifi_update_dynamic_dns", product="network", category="dynamic_dns", manager="", method="")
    registry = _registry_with(entry)
    factory, domain_manager = _ddns_factory()

    with pytest.raises(ValueError, match="Unknown or read-only fields"):
        await dispatch_action(
            registry=registry,
            factory=factory,
            session=MagicMock(),
            tool_name="unifi_update_dynamic_dns",
            controller_id="cid",
            controller_products=["network"],
            site="default",
            args={"entry_id": "ddns001", "update_data": {"id": "x", "service": "noip"}},
            confirm=True,
            dispatch_table={
                "unifi_update_dynamic_dns": DispatchEntry(
                    manager_attr="dynamic_dns_manager", method="update_dynamic_dns"
                )
            },
        )
    domain_manager.update_dynamic_dns.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_translates_dynamic_dns_create_to_controller_payload() -> None:
    """unifi_create_dynamic_dns: the translator must validate + translate entry_data
    to the controller create payload (single positional arg), so unknown keys are
    not forwarded raw to the controller on the /v1/actions path."""
    entry = ToolEntry(name="unifi_create_dynamic_dns", product="network", category="dynamic_dns", manager="", method="")
    registry = _registry_with(entry)
    factory, domain_manager = _ddns_factory()

    await dispatch_action(
        registry=registry,
        factory=factory,
        session=MagicMock(),
        tool_name="unifi_create_dynamic_dns",
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args={"entry_data": {"host_name": "home.example.com", "service": "dyndns", "interface": "wan"}},
        confirm=True,
        dispatch_table={
            "unifi_create_dynamic_dns": DispatchEntry(manager_attr="dynamic_dns_manager", method="create_dynamic_dns")
        },
    )

    domain_manager.create_dynamic_dns.assert_awaited_once()
    (positional, keyword) = domain_manager.create_dynamic_dns.await_args
    assert keyword == {}, f"expected no kwargs; got {keyword}"
    assert positional[0] == {"host_name": "home.example.com", "service": "dyndns", "interface": "wan"}


@pytest.mark.asyncio
async def test_dispatch_dynamic_dns_create_rejects_unknown_field() -> None:
    """Unknown keys in entry_data must fail rather than being forwarded raw to the controller."""
    entry = ToolEntry(name="unifi_create_dynamic_dns", product="network", category="dynamic_dns", manager="", method="")
    registry = _registry_with(entry)
    factory, domain_manager = _ddns_factory()

    with pytest.raises(ValueError, match="Unknown or read-only fields"):
        await dispatch_action(
            registry=registry,
            factory=factory,
            session=MagicMock(),
            tool_name="unifi_create_dynamic_dns",
            controller_id="cid",
            controller_products=["network"],
            site="default",
            args={"entry_data": {"host_name": "home.example.com", "service": "dyndns", "bogus_field": "x"}},
            confirm=True,
            dispatch_table={
                "unifi_create_dynamic_dns": DispatchEntry(
                    manager_attr="dynamic_dns_manager", method="create_dynamic_dns"
                )
            },
        )
    domain_manager.create_dynamic_dns.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_acl_update_clears_netmask() -> None:
    """clear_destination_netmask flows through the API translator to a None mac_mask sentinel."""
    entry = ToolEntry(name="unifi_update_acl_rule", product="network", category="acl_rules", manager="", method="")
    registry = _registry_with(entry)
    domain_manager = MagicMock()
    domain_manager.update_acl_rule = AsyncMock(return_value={"_id": "r1"})
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
        tool_name="unifi_update_acl_rule",
        controller_id="cid",
        controller_products=["network"],
        site="default",
        # clear (top-level) alongside a sibling field change (nested in rule_data) — both must come through
        args={"rule_id": "r1", "rule_data": {"name": "renamed"}, "clear_destination_netmask": True},
        confirm=True,
        dispatch_table={"unifi_update_acl_rule": DispatchEntry(manager_attr="acl_manager", method="update_acl_rule")},
    )
    (positional, _) = domain_manager.update_acl_rule.await_args
    payload = positional[1]
    assert payload["traffic_destination"]["mac_mask"] is None  # clear sentinel
    assert payload["name"] == "renamed"  # sibling field preserved alongside the clear


@pytest.mark.asyncio
async def test_dispatch_acl_update_rejects_empty() -> None:
    """A no-field, no-clear update is rejected (parity with the MCP tool), not a silent no-op."""
    entry = ToolEntry(name="unifi_update_acl_rule", product="network", category="acl_rules", manager="", method="")
    registry = _registry_with(entry)
    domain_manager = MagicMock()
    domain_manager.update_acl_rule = AsyncMock(return_value={"_id": "r1"})
    conn_manager = MagicMock()
    conn_manager.site = "default"
    conn_manager.set_site = AsyncMock()
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=domain_manager)
    factory.get_connection_manager = AsyncMock(return_value=conn_manager)

    with pytest.raises(ValueError, match="No fields"):
        await dispatch_action(
            registry=registry,
            factory=factory,
            session=MagicMock(),
            tool_name="unifi_update_acl_rule",
            controller_id="cid",
            controller_products=["network"],
            site="default",
            args={"rule_id": "r1"},
            confirm=True,
            dispatch_table={
                "unifi_update_acl_rule": DispatchEntry(manager_attr="acl_manager", method="update_acl_rule")
            },
        )
    domain_manager.update_acl_rule.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_acl_update_rejects_bad_netmask() -> None:
    """An out-of-range netmask via the API update path raises a clean ValueError (the route layer
    converts it to an error envelope) rather than reaching netmask_to_mac_mask unvalidated."""
    entry = ToolEntry(name="unifi_update_acl_rule", product="network", category="acl_rules", manager="", method="")
    registry = _registry_with(entry)
    domain_manager = MagicMock()
    domain_manager.update_acl_rule = AsyncMock(return_value={"_id": "r1"})
    conn_manager = MagicMock()
    conn_manager.site = "default"
    conn_manager.set_site = AsyncMock()
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=domain_manager)
    factory.get_connection_manager = AsyncMock(return_value=conn_manager)

    with pytest.raises(ValueError, match="netmask"):
        await dispatch_action(
            registry=registry,
            factory=factory,
            session=MagicMock(),
            tool_name="unifi_update_acl_rule",
            controller_id="cid",
            controller_products=["network"],
            site="default",
            args={"rule_id": "r1", "rule_data": {"destination_netmask": 99}},
            confirm=True,
            dispatch_table={
                "unifi_update_acl_rule": DispatchEntry(manager_attr="acl_manager", method="update_acl_rule")
            },
        )
    domain_manager.update_acl_rule.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_acl_update_rejects_read_only_nested_field() -> None:
    """The API translator must reject read-only fields nested in rule_data, matching the MCP tool."""
    entry = ToolEntry(name="unifi_update_acl_rule", product="network", category="acl_rules", manager="", method="")
    registry = _registry_with(entry)
    domain_manager = MagicMock()
    domain_manager.update_acl_rule = AsyncMock(return_value={"_id": "r1"})
    conn_manager = MagicMock(site="default")
    conn_manager.set_site = AsyncMock()
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=domain_manager)
    factory.get_connection_manager = AsyncMock(return_value=conn_manager)

    with pytest.raises(ValueError, match="Unknown or read-only fields"):
        await dispatch_action(
            registry=registry,
            factory=factory,
            session=MagicMock(),
            tool_name="unifi_update_acl_rule",
            controller_id="cid",
            controller_products=["network"],
            site="default",
            args={"rule_id": "r1", "rule_data": {"source_mac_mask": "ff:ff:ff:00:00:00"}},
            confirm=True,
            dispatch_table={
                "unifi_update_acl_rule": DispatchEntry(manager_attr="acl_manager", method="update_acl_rule")
            },
        )
    domain_manager.update_acl_rule.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_acl_update_rejects_unknown_nested_field() -> None:
    """Unknown fields nested in rule_data must fail instead of being silently dropped."""
    entry = ToolEntry(name="unifi_update_acl_rule", product="network", category="acl_rules", manager="", method="")
    registry = _registry_with(entry)
    domain_manager = MagicMock()
    domain_manager.update_acl_rule = AsyncMock(return_value={"_id": "r1"})
    conn_manager = MagicMock(site="default")
    conn_manager.set_site = AsyncMock()
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=domain_manager)
    factory.get_connection_manager = AsyncMock(return_value=conn_manager)

    with pytest.raises(ValueError, match="Unknown or read-only fields"):
        await dispatch_action(
            registry=registry,
            factory=factory,
            session=MagicMock(),
            tool_name="unifi_update_acl_rule",
            controller_id="cid",
            controller_products=["network"],
            site="default",
            args={"rule_id": "r1", "rule_data": {"bogus": "ignored-before"}},
            confirm=True,
            dispatch_table={
                "unifi_update_acl_rule": DispatchEntry(manager_attr="acl_manager", method="update_acl_rule")
            },
        )
    domain_manager.update_acl_rule.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_acl_update_netmask_none_is_noop_field() -> None:
    """source_netmask=None remains a safe no-op update field, matching the MCP tool's round-trip behavior."""
    entry = ToolEntry(name="unifi_update_acl_rule", product="network", category="acl_rules", manager="", method="")
    registry = _registry_with(entry)
    domain_manager = MagicMock()
    domain_manager.update_acl_rule = AsyncMock(return_value={"_id": "r1"})
    conn_manager = MagicMock(site="default")
    conn_manager.set_site = AsyncMock()
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=domain_manager)
    factory.get_connection_manager = AsyncMock(return_value=conn_manager)

    await dispatch_action(
        registry=registry,
        factory=factory,
        session=MagicMock(),
        tool_name="unifi_update_acl_rule",
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args={"rule_id": "r1", "rule_data": {"source_netmask": None}},
        confirm=True,
        dispatch_table={"unifi_update_acl_rule": DispatchEntry(manager_attr="acl_manager", method="update_acl_rule")},
    )
    (positional, _) = domain_manager.update_acl_rule.await_args
    assert positional == ("r1", {})


@pytest.mark.asyncio
async def test_dispatch_delete_acl_passes_rule_id_unchanged() -> None:
    """unifi_delete_acl_rule already aligns: manager takes rule_id as the only
    kwarg, so the default **args dispatch works. No translator needed."""
    entry = ToolEntry(
        name="unifi_delete_acl_rule",
        product="network",
        category="acl_rules",
        manager="",
        method="",
    )
    registry = _registry_with(entry)

    domain_manager = MagicMock()
    domain_manager.delete_acl_rule = AsyncMock(return_value=True)

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
        tool_name="unifi_delete_acl_rule",
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args={"rule_id": "r1"},
        confirm=True,
        dispatch_table={
            "unifi_delete_acl_rule": DispatchEntry(manager_attr="acl_manager", method="delete_acl_rule"),
        },
    )

    domain_manager.delete_acl_rule.assert_awaited_once_with(rule_id="r1")


@pytest.mark.asyncio
async def test_dispatch_translates_export_clip_iso_to_datetime() -> None:
    """protect_export_clip: action endpoint sends ISO strings; manager
    expects datetime. The translator must parse before invocation."""
    from datetime import datetime, timezone

    entry = ToolEntry(
        name="protect_export_clip",
        product="protect",
        category="recordings",
        manager="",
        method="",
    )
    registry = _registry_with(entry)

    domain_manager = MagicMock()
    domain_manager.export_clip = AsyncMock(return_value={"ok": True})

    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=domain_manager)
    factory.get_connection_manager = AsyncMock(return_value=MagicMock(site=None))

    await dispatch_action(
        registry=registry,
        factory=factory,
        session=MagicMock(),
        tool_name="protect_export_clip",
        controller_id="cid",
        controller_products=["protect"],
        site="default",
        args={
            "camera_id": "cam001",
            "start": "2026-05-13T12:00:00Z",
            "end": "2026-05-13T12:30:00Z",
            "channel_index": 0,
            "fps": 4,
        },
        confirm=True,
        dispatch_table={
            "protect_export_clip": DispatchEntry(manager_attr="recording_manager", method="export_clip"),
        },
    )

    domain_manager.export_clip.assert_awaited_once()
    (positional, keyword) = domain_manager.export_clip.await_args
    assert positional == ()
    assert keyword["camera_id"] == "cam001"
    assert isinstance(keyword["start"], datetime)
    assert keyword["start"] == datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
    assert isinstance(keyword["end"], datetime)
    assert keyword["channel_index"] == 0
    assert keyword["fps"] == 4


@pytest.mark.asyncio
async def test_dispatch_translates_delete_recording_iso_to_datetime() -> None:
    """protect_delete_recording: same datetime parsing pattern as export_clip."""
    from datetime import datetime, timezone

    entry = ToolEntry(
        name="protect_delete_recording",
        product="protect",
        category="recordings",
        manager="",
        method="",
    )
    registry = _registry_with(entry)

    domain_manager = MagicMock()
    domain_manager.delete_recording = AsyncMock(return_value={"ok": True})

    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=domain_manager)
    factory.get_connection_manager = AsyncMock(return_value=MagicMock(site=None))

    await dispatch_action(
        registry=registry,
        factory=factory,
        session=MagicMock(),
        tool_name="protect_delete_recording",
        controller_id="cid",
        controller_products=["protect"],
        site="default",
        args={
            "camera_id": "cam001",
            "start": "2026-05-13T00:00:00+00:00",
            "end": "2026-05-13T12:00:00+00:00",
        },
        confirm=True,
        dispatch_table={
            "protect_delete_recording": DispatchEntry(manager_attr="recording_manager", method="delete_recording"),
        },
    )

    domain_manager.delete_recording.assert_awaited_once()
    (positional, keyword) = domain_manager.delete_recording.await_args
    assert positional == ()
    assert isinstance(keyword["start"], datetime)
    assert isinstance(keyword["end"], datetime)
    assert keyword["start"].tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# Network client tools — mac_address → client_mac rename
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_translates_block_client_mac_address_to_client_mac() -> None:
    """unifi_block_client: LLM sends mac_address; manager.block_client expects client_mac."""
    entry = ToolEntry(
        name="unifi_block_client",
        product="network",
        category="clients",
        manager="",
        method="",
    )
    registry = _registry_with(entry)

    domain_manager = MagicMock()
    domain_manager.block_client = AsyncMock(return_value=True)

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
        tool_name="unifi_block_client",
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args={"mac_address": "aa:bb:cc:dd:ee:ff"},
        confirm=True,
        dispatch_table={
            "unifi_block_client": DispatchEntry(manager_attr="client_manager", method="block_client"),
        },
    )

    domain_manager.block_client.assert_awaited_once_with(client_mac="aa:bb:cc:dd:ee:ff")


@pytest.mark.asyncio
async def test_dispatch_translates_unblock_client_mac_address_to_client_mac() -> None:
    """unifi_unblock_client: same mac_address → client_mac rename."""
    entry = ToolEntry(
        name="unifi_unblock_client",
        product="network",
        category="clients",
        manager="",
        method="",
    )
    registry = _registry_with(entry)

    domain_manager = MagicMock()
    domain_manager.unblock_client = AsyncMock(return_value=True)

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
        tool_name="unifi_unblock_client",
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args={"mac_address": "aa:bb:cc:dd:ee:ff"},
        confirm=True,
        dispatch_table={
            "unifi_unblock_client": DispatchEntry(manager_attr="client_manager", method="unblock_client"),
        },
    )

    domain_manager.unblock_client.assert_awaited_once_with(client_mac="aa:bb:cc:dd:ee:ff")


@pytest.mark.asyncio
async def test_dispatch_translates_rename_client_mac_address_to_client_mac() -> None:
    """unifi_rename_client: mac_address → client_mac; name passes through."""
    entry = ToolEntry(
        name="unifi_rename_client",
        product="network",
        category="clients",
        manager="",
        method="",
    )
    registry = _registry_with(entry)

    domain_manager = MagicMock()
    domain_manager.rename_client = AsyncMock(return_value=True)

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
        tool_name="unifi_rename_client",
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args={"mac_address": "aa:bb:cc:dd:ee:ff", "name": "Living Room TV"},
        confirm=True,
        dispatch_table={
            "unifi_rename_client": DispatchEntry(manager_attr="client_manager", method="rename_client"),
        },
    )

    domain_manager.rename_client.assert_awaited_once_with(client_mac="aa:bb:cc:dd:ee:ff", name="Living Room TV")


@pytest.mark.asyncio
async def test_dispatch_translates_authorize_guest_mac_address_to_client_mac() -> None:
    """unifi_authorize_guest: mac_address → client_mac; bandwidth kwargs pass through."""
    entry = ToolEntry(
        name="unifi_authorize_guest",
        product="network",
        category="clients",
        manager="",
        method="",
    )
    registry = _registry_with(entry)

    domain_manager = MagicMock()
    domain_manager.authorize_guest = AsyncMock(return_value=True)

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
        tool_name="unifi_authorize_guest",
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args={
            "mac_address": "aa:bb:cc:dd:ee:ff",
            "minutes": 480,
            "up_kbps": 5000,
            "down_kbps": 10000,
        },
        confirm=True,
        dispatch_table={
            "unifi_authorize_guest": DispatchEntry(manager_attr="client_manager", method="authorize_guest"),
        },
    )

    domain_manager.authorize_guest.assert_awaited_once_with(
        client_mac="aa:bb:cc:dd:ee:ff",
        minutes=480,
        up_kbps=5000,
        down_kbps=10000,
    )


@pytest.mark.asyncio
async def test_dispatch_translates_set_client_ip_settings_mac_address_to_client_mac() -> None:
    """unifi_set_client_ip_settings: mac_address → client_mac; IP fields pass through."""
    entry = ToolEntry(
        name="unifi_set_client_ip_settings",
        product="network",
        category="clients",
        manager="",
        method="",
    )
    registry = _registry_with(entry)

    domain_manager = MagicMock()
    domain_manager.set_client_ip_settings = AsyncMock(return_value=True)

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
        tool_name="unifi_set_client_ip_settings",
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args={
            "mac_address": "aa:bb:cc:dd:ee:ff",
            "use_fixedip": True,
            "fixed_ip": "192.168.1.50",
        },
        confirm=True,
        dispatch_table={
            "unifi_set_client_ip_settings": DispatchEntry(
                manager_attr="client_manager", method="set_client_ip_settings"
            ),
        },
    )

    domain_manager.set_client_ip_settings.assert_awaited_once_with(
        client_mac="aa:bb:cc:dd:ee:ff",
        use_fixedip=True,
        fixed_ip="192.168.1.50",
    )


# ---------------------------------------------------------------------------
# Network — update_firewall_policy: update_data → updates rename
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_translates_update_firewall_policy_update_data_to_updates() -> None:
    """unifi_update_firewall_policy: tool sends update_data; manager takes updates."""
    entry = ToolEntry(
        name="unifi_update_firewall_policy",
        product="network",
        category="firewall_policies",
        manager="",
        method="",
    )
    registry = _registry_with(entry)

    domain_manager = MagicMock()
    domain_manager.update_firewall_policy = AsyncMock(return_value=True)

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
        tool_name="unifi_update_firewall_policy",
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args={"policy_id": "p1", "update_data": {"enabled": False}},
        confirm=True,
        dispatch_table={
            "unifi_update_firewall_policy": DispatchEntry(
                manager_attr="firewall_manager", method="update_firewall_policy"
            ),
        },
    )

    domain_manager.update_firewall_policy.assert_awaited_once_with(policy_id="p1", updates={"enabled": False})


# ---------------------------------------------------------------------------
# Network — toggle_port_forward: port_forward_id → rule_id rename
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_translates_toggle_port_forward_id_to_rule_id() -> None:
    """unifi_toggle_port_forward: tool sends port_forward_id; manager takes rule_id."""
    entry = ToolEntry(
        name="unifi_toggle_port_forward",
        product="network",
        category="port_forwards",
        manager="",
        method="",
    )
    registry = _registry_with(entry)

    domain_manager = MagicMock()
    domain_manager.toggle_port_forward = AsyncMock(return_value=True)

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
        tool_name="unifi_toggle_port_forward",
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args={"port_forward_id": "pf001"},
        confirm=True,
        dispatch_table={
            "unifi_toggle_port_forward": DispatchEntry(manager_attr="firewall_manager", method="toggle_port_forward"),
        },
    )

    domain_manager.toggle_port_forward.assert_awaited_once_with(rule_id="pf001")


@pytest.mark.asyncio
async def test_dispatch_translates_delete_port_forward_id_to_rule_id() -> None:
    """unifi_delete_port_forward: tool sends port_forward_id; manager takes rule_id."""
    entry = ToolEntry(
        name="unifi_delete_port_forward",
        product="network",
        category="port_forwards",
        manager="",
        method="",
    )
    registry = _registry_with(entry)

    domain_manager = MagicMock()
    domain_manager.delete_port_forward = AsyncMock(return_value=True)

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
        tool_name="unifi_delete_port_forward",
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args={"port_forward_id": "pf001"},
        confirm=True,
        dispatch_table={
            "unifi_delete_port_forward": DispatchEntry(manager_attr="firewall_manager", method="delete_port_forward"),
        },
    )

    domain_manager.delete_port_forward.assert_awaited_once_with(rule_id="pf001")


# ---------------------------------------------------------------------------
# Network — update_device_radio: flatten to (device_mac, radio_id, updates)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_translates_update_device_radio_to_manager_shape() -> None:
    """unifi_update_device_radio: flat kwargs → (device_mac, radio_id, updates)."""
    entry = ToolEntry(
        name="unifi_update_device_radio",
        product="network",
        category="devices",
        manager="",
        method="",
    )
    registry = _registry_with(entry)

    domain_manager = MagicMock()
    domain_manager.update_device_radio = AsyncMock(return_value=True)

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
        tool_name="unifi_update_device_radio",
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args={
            "mac_address": "aa:bb:cc:dd:ee:ff",
            "radio": "na",
            "tx_power_mode": "auto",
            "channel": 36,
        },
        confirm=True,
        dispatch_table={
            "unifi_update_device_radio": DispatchEntry(manager_attr="device_manager", method="update_device_radio"),
        },
    )

    domain_manager.update_device_radio.assert_awaited_once_with(
        device_mac="aa:bb:cc:dd:ee:ff",
        radio_id="na",
        updates={"tx_power_mode": "auto", "channel": 36},
    )


# ---------------------------------------------------------------------------
# Network — get_top_clients: duration string → duration_hours integer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_translates_get_top_clients_duration_to_hours() -> None:
    """unifi_get_top_clients: duration='daily' → duration_hours=24."""
    entry = ToolEntry(
        name="unifi_get_top_clients",
        product="network",
        category="stats",
        manager="",
        method="",
    )
    registry = _registry_with(entry)

    domain_manager = MagicMock()
    domain_manager.get_top_clients = AsyncMock(return_value=[])

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
        tool_name="unifi_get_top_clients",
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args={"duration": "weekly", "limit": 5},
        confirm=False,
        dispatch_table={
            "unifi_get_top_clients": DispatchEntry(manager_attr="stats_manager", method="get_top_clients"),
        },
    )

    domain_manager.get_top_clients.assert_awaited_once_with(duration_hours=168, limit=5)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "args", "expected_method", "expected_kwargs"),
    [
        (
            "unifi_reboot_device",
            {"mac_address": "aa:bb:cc:dd:ee:ff"},
            "reboot_device",
            {"device_mac": "aa:bb:cc:dd:ee:ff"},
        ),
        (
            "access_create_credential",
            {"credential_type": "pin", "credential_data": {"pin_code": "1234"}},
            "apply_create_credential",
            {"credential_type": "pin", "data": {"pin_code": "1234"}},
        ),
        (
            "protect_alarm_create_rule",
            {"body": {"name": "Front door", "actions": [{"type": "webhook"}]}},
            "create_rule",
            {"fields": {"name": "Front door", "actions": [{"type": "webhook"}]}},
        ),
        (
            "unifi_set_outlet_state",
            {
                "mac_address": "aa:bb:cc:dd:ee:ff",
                "outlet_index": 2,
                "relay_state": False,
                "cycle_enabled": True,
            },
            "set_outlet_state",
            {
                "device_mac": "aa:bb:cc:dd:ee:ff",
                "outlet_index": 2,
                "relay_state": False,
                "cycle_enabled": True,
            },
        ),
        (
            "unifi_update_port_forward",
            {"port_forward_id": "pf-1", "update_data": {"enabled": False}},
            "update_port_forward",
            {"rule_id": "pf-1", "updates": {"enabled": False}},
        ),
        (
            "unifi_toggle_qos_rule_enabled",
            {"rule_id": "qos-1"},
            "toggle_qos_rule_enabled",
            {"rule_id": "qos-1"},
        ),
    ],
    ids=[
        "network-identifier-alias",
        "access-payload-alias",
        "protect-payload-alias",
        "outlet-mutation-binding",
        "port-forward-mutation-binding",
        "qos-toggle-bridge",
    ],
)
async def test_reviewed_catalog_mutations_reach_the_intended_core_signature(
    tool_name: str,
    args: dict,
    expected_method: str,
    expected_kwargs: dict,
) -> None:
    """Regression coverage for failures found by the independent catalog review."""
    entry = PRODUCTION_REGISTRY.resolve(tool_name)
    manager = MagicMock()
    manager_result = ({"ok": True}, True) if tool_name.startswith("protect_alarm_") else {"ok": True}
    manager_method = AsyncMock(return_value=manager_result)
    setattr(manager, expected_method, manager_method)
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)
    factory.get_connection_manager = AsyncMock(return_value=MagicMock(site="default"))

    result = await dispatch_action(
        registry=PRODUCTION_REGISTRY,
        factory=factory,
        session=MagicMock(),
        tool_name=tool_name,
        controller_id="cid",
        controller_products=[entry.product],
        site="default",
        args=args,
        confirm=True,
    )

    assert result == {"ok": True}
    manager_method.assert_awaited_once_with(**expected_kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "args", "expected_method", "expected_kwargs"),
    [
        (
            "unifi_create_client_group",
            {"name": "Kids", "members": ["aa:bb:cc:dd:ee:ff"]},
            "create_client_group",
            {"group_data": {"name": "Kids", "members": ["aa:bb:cc:dd:ee:ff"], "type": "CLIENTS"}},
        ),
        (
            "unifi_create_port_forward",
            {
                "port_forward_data": {
                    "name": "HTTPS",
                    "dst_port": "443",
                    "fwd_port": "8443",
                    "fwd_ip": "192.168.1.20",
                    "protocol": "tcp_udp",
                }
            },
            "create_port_forward",
            {
                "rule_data": {
                    "name": "HTTPS",
                    "dst_port": "443",
                    "fwd_port": "8443",
                    "fwd": "192.168.1.20",
                    "proto": "tcp/udp",
                    "enabled": True,
                    "log": False,
                    "protocol_match_excepted": False,
                }
            },
        ),
        (
            "unifi_create_simple_port_forward",
            {"rule": {"name": "HTTP", "ext_port": "80", "to_ip": "192.168.1.21"}},
            "create_port_forward",
            {
                "rule_data": {
                    "name": "HTTP",
                    "dst_port": "80",
                    "fwd_port": "80",
                    "fwd": "192.168.1.21",
                    "proto": "tcp/udp",
                    "enabled": True,
                    "log": False,
                    "protocol_match_excepted": False,
                }
            },
        ),
        (
            "unifi_create_simple_qos_rule",
            {
                "rule": {
                    "name": "Video",
                    "interface": "wan",
                    "direction": "download",
                    "limit_kbps": 5000,
                    "target": {"type": "ip", "value": "192.168.1.50"},
                }
            },
            "create_qos_rule",
            {
                "rule_data": {
                    "name": "Video",
                    "interface": "wan",
                    "direction": "download",
                    "bandwidth_limit_kbps": 5000,
                    "enabled": True,
                    "target_ip_address": "192.168.1.50",
                }
            },
        ),
        (
            "unifi_update_port_forward",
            {
                "port_forward_id": "pf-1",
                "update_data": {"protocol": "udp", "src_ip": "", "enabled": False},
            },
            "update_port_forward",
            {"rule_id": "pf-1", "updates": {"proto": "udp", "src": None, "enabled": False}},
        ),
        (
            "unifi_update_firewall_policy",
            {
                "policy_id": "p-1",
                "update_data": {
                    "action": "allow",
                    "ip_version": "IPv4",
                    "connection_state_type": "custom",
                    "connection_states": ["new"],
                },
            },
            "update_firewall_policy",
            {
                "policy_id": "p-1",
                "updates": {
                    "action": "ALLOW",
                    "ip_version": "IPV4",
                    "connection_state_type": "CUSTOM",
                    "connection_states": ["NEW"],
                },
            },
        ),
        (
            "unifi_update_content_filter",
            {
                "filter_id": "cf-1",
                "filter_data": {"blocked_categories": ["ADULT"], "schedule_mode": "ALWAYS"},
            },
            "update_content_filter",
            {"filter_id": "cf-1", "update_data": {"categories": ["ADULT"], "schedule": {"mode": "ALWAYS"}}},
        ),
    ],
)
async def test_reviewed_catalog_mutations_preserve_wrapper_semantics(
    tool_name: str,
    args: dict,
    expected_method: str,
    expected_kwargs: dict,
) -> None:
    entry = PRODUCTION_REGISTRY.resolve(tool_name)
    manager = MagicMock()
    manager_method = AsyncMock(return_value={"ok": True})
    setattr(manager, expected_method, manager_method)
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)
    factory.get_connection_manager = AsyncMock(return_value=MagicMock(site="default"))

    await dispatch_action(
        registry=PRODUCTION_REGISTRY,
        factory=factory,
        session=MagicMock(),
        tool_name=tool_name,
        controller_id="cid",
        controller_products=[entry.product],
        site="default",
        args=args,
        confirm=True,
    )

    manager_method.assert_awaited_once_with(**expected_kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "tool_name",
        "args",
        "method_name",
        "manager_result",
        "expected_manager_kwargs",
        "data_key",
        "expected_payload",
    ),
    [
        (
            "unifi_list_clients",
            {
                "filter_type": "wireless",
                "include_offline": True,
                "search": "phone",
                "limit": 1,
                "fields": "mac,connection_type",
            },
            "get_clients",
            [{"mac": "aa", "name": "Phone", "is_wired": False}],
            {"include_offline": True},
            "clients",
            {"filter_type": "wireless", "search": "phone", "limit": 1, "returned_count": 1},
        ),
        (
            "unifi_get_alerts",
            {"limit": 1, "include_archived": True},
            "get_alerts",
            [{"id": "a1"}, {"id": "a2"}],
            {"include_archived": True},
            "alerts",
            {"limit": 1, "include_archived": True},
        ),
        (
            "unifi_get_client_details",
            {"mac_address": "aa", "include": "wireless", "summary": True},
            "get_client_details",
            {"mac": "aa", "is_wired": False, "signal": -42},
            {"client_mac": "aa"},
            "client",
            {"include": "wireless", "summary_mode": True},
        ),
        (
            "unifi_get_dashboard",
            {"history_seconds": 3600, "summary": False},
            "get_dashboard",
            [{"wan_activity": [1], "num_sta": 2}],
            {"history_seconds": 3600},
            "dashboard",
            {"history_seconds": 3600, "summary_mode": False, "omitted_sections": []},
        ),
        (
            "unifi_get_device_details",
            {"mac_address": "bb", "include": "ports", "summary": True},
            "get_device_details",
            {"mac": "bb", "type": "usw", "port_table": []},
            {"device_mac": "bb"},
            "device",
            {"include": "ports", "summary_mode": True},
        ),
        (
            "unifi_get_network_details",
            {"network_id": "n1", "include": "dhcp", "summary": True},
            "get_network_details",
            {"_id": "n1", "name": "LAN", "dhcpd_enabled": True},
            {"network_id": "n1"},
            "details",
            {"network_id": "n1", "include": "dhcp", "summary_mode": True},
        ),
        (
            "unifi_list_devices",
            {
                "device_type": "switch",
                "status": "online",
                "search": "office",
                "limit": 1,
                "include_details": True,
                "summary": False,
            },
            "get_devices",
            [{"mac": "cc", "name": "Office", "type": "usw", "state": 1, "port_table": []}],
            {},
            "devices",
            {
                "filter_type": "switch",
                "filter_status": "online",
                "search": "office",
                "limit": 1,
                "returned_count": 1,
            },
        ),
        (
            "unifi_list_firewall_policies",
            {
                "search": "guest",
                "action": "allow",
                "enabled_only": True,
                "limit": 1,
                "summary": False,
                "include_predefined": True,
            },
            "get_firewall_policies",
            [{"_id": "p1", "name": "Guest", "enabled": True, "action": "ALLOW", "index": 1}],
            {"include_predefined": True},
            "policies",
            {"search": "guest", "action_filter": "allow", "enabled_only": True, "limit": 1},
        ),
        (
            "unifi_list_networks",
            {"search": "20", "purpose": "guest", "limit": 1, "fields": "_id,name"},
            "get_networks",
            [{"_id": "n1", "name": "Guest", "purpose": "guest", "vlan": 20}],
            {},
            "networks",
            {"search": "20", "purpose_filter": "guest", "fields": "_id,name", "limit": 1},
        ),
        (
            "unifi_list_rogue_aps",
            {"within_hours": 12, "channel": 36, "min_signal": -70, "limit": 1, "offset": 1, "summary": False},
            "list_rogue_aps",
            [
                {"bssid": "one", "channel": 36, "signal": -60},
                {"bssid": "two", "channel": 36, "signal": -50},
            ],
            {"within_hours": 12},
            "rogue_aps",
            {"within_hours": 12, "summary_mode": False, "limit": 1, "offset": 1},
        ),
        (
            "unifi_list_wlans",
            {"search": "guest", "enabled_only": True, "limit": 1},
            "get_wlans",
            [{"_id": "w1", "name": "Guest", "enabled": True}],
            {},
            "wlans",
            {"search": "guest", "enabled_only": True, "limit": 1, "returned_count": 1},
        ),
    ],
)
async def test_read_action_non_default_parameters_share_core_view_contract(
    tool_name: str,
    args: dict,
    method_name: str,
    manager_result: object,
    expected_manager_kwargs: dict,
    data_key: str,
    expected_payload: dict,
) -> None:
    entry = PRODUCTION_REGISTRY.resolve(tool_name)
    manager = MagicMock()
    manager._connection.site = "default"
    method = AsyncMock(return_value=manager_result)
    setattr(manager, method_name, method)
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)

    result = await dispatch_action(
        registry=PRODUCTION_REGISTRY,
        factory=factory,
        session=MagicMock(),
        tool_name=tool_name,
        controller_id="cid",
        controller_products=[entry.product],
        site="default",
        args=args,
        confirm=False,
    )

    assert isinstance(result, ShapedReadResult)
    assert result.data_key == data_key
    assert result.payload["success"] is True
    assert data_key in result.payload
    for key, value in expected_payload.items():
        assert result.payload[key] == value
    if tool_name == "unifi_list_firewall_policies":
        assert result.render_hint["display_columns"][-1] == "index"
        assert result.render_hint["sort_default"] == "index:asc"
    if tool_name == "unifi_list_rogue_aps":
        assert "essid" in result.render_hint["display_columns"]
        assert "ssid" not in result.render_hint["display_columns"]
    method.assert_awaited_once_with(**expected_manager_kwargs)


@pytest.mark.asyncio
async def test_snapshot_reference_does_not_fetch_image_bytes() -> None:
    entry = PRODUCTION_REGISTRY.resolve("protect_get_snapshot")
    factory = MagicMock()

    result = await dispatch_action(
        registry=PRODUCTION_REGISTRY,
        factory=factory,
        session=MagicMock(),
        tool_name=entry.name,
        controller_id="cid",
        controller_products=[entry.product],
        site="default",
        args={"camera_id": "camera-1"},
        confirm=False,
    )

    assert result == {"snapshot_url": "protect://cameras/camera-1/snapshot"}
    factory.get_domain_manager.assert_not_called()


@pytest.mark.asyncio
async def test_snapshot_image_result_is_base64_encoded() -> None:
    entry = PRODUCTION_REGISTRY.resolve("protect_get_snapshot")
    manager = MagicMock()
    manager.get_snapshot = AsyncMock(return_value=b"jpeg-data")
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)

    result = await dispatch_action(
        registry=PRODUCTION_REGISTRY,
        factory=factory,
        session=MagicMock(),
        tool_name=entry.name,
        controller_id="cid",
        controller_products=[entry.product],
        site="default",
        args={"camera_id": "camera-1", "include_image": True},
        confirm=False,
    )

    assert result == {
        "image_base64": base64.b64encode(b"jpeg-data").decode(),
        "content_type": "image/jpeg",
    }
    manager.get_snapshot.assert_awaited_once_with(camera_id="camera-1")


@pytest.mark.asyncio
async def test_recent_events_strips_internal_and_unrequested_metadata() -> None:
    entry = PRODUCTION_REGISTRY.resolve("protect_recent_events")
    manager = MagicMock(buffer_size=2)
    manager.get_recent_from_buffer.return_value = [
        {"id": "event-1", "type": "motion", "_buffered_at": 123, "metadata": {"weather": "rain"}}
    ]
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)

    result = await dispatch_action(
        registry=PRODUCTION_REGISTRY,
        factory=factory,
        session=MagicMock(),
        tool_name=entry.name,
        controller_id="cid",
        controller_products=[entry.product],
        site="default",
        args={},
        confirm=False,
    )

    assert result == {
        "events": [{"id": "event-1", "type": "motion", "smart_detect_types": []}],
        "count": 1,
        "source": "websocket_buffer",
        "buffer_size": 2,
    }


@pytest.mark.parametrize(
    ("tool_name", "args", "expected_kwargs"),
    [
        (
            "unifi_create_oon_policy",
            {
                "name": "Kids",
                "target_type": "clients",
                "targets": ["aa:bb:cc:dd:ee:ff"],
                "secure": {"internet_access_enabled": False},
            },
            {
                "policy_data": {
                    "name": "Kids",
                    "enabled": True,
                    "target_type": "CLIENTS",
                    "targets": ["aa:bb:cc:dd:ee:ff"],
                    "secure": {"internet_access_enabled": False},
                }
            },
        ),
        (
            "unifi_create_qos_rule",
            {
                "qos_data": {
                    "name": "Voice",
                    "interface": "wan",
                    "direction": "upload",
                    "bandwidth_limit_kbps": 1000,
                    "id": "read-only",
                }
            },
            {
                "rule_data": {
                    "name": "Voice",
                    "interface": "wan",
                    "direction": "upload",
                    "bandwidth_limit_kbps": 1000,
                    "enabled": True,
                }
            },
        ),
        (
            "unifi_update_autobackup_settings",
            {"update_data": {"autobackup_enabled": False, "unknown": "drop"}},
            {"settings": {"autobackup_enabled": False}},
        ),
        (
            "unifi_update_client_group",
            {"group_id": "g-1", "group_data": {"name": "New", "id": "read-only"}},
            {"group_id": "g-1", "update_data": {"name": "New"}},
        ),
        (
            "unifi_update_dns_record",
            {"record_id": "d-1", "update_data": {"ttl": 60, "id": "read-only"}},
            {"record_id": "d-1", "record_data": {"ttl": 60}},
        ),
        (
            "unifi_update_oon_policy",
            {"policy_id": "o-1", "policy_data": {"enabled": False, "id": "read-only"}},
            {"policy_id": "o-1", "update_data": {"enabled": False}},
        ),
        (
            "unifi_update_port_profile",
            {"profile_id": "p-1", "profile_data": {"poe_mode": "off", "id": "read-only"}},
            {"profile_id": "p-1", "update_data": {"poe_mode": "off"}},
        ),
        (
            "unifi_update_device_radio",
            {
                "mac_address": "aa:bb:cc:dd:ee:ff",
                "radio": "na",
                "channel": 36,
                "unknown": "drop",
            },
            {"device_mac": "aa:bb:cc:dd:ee:ff", "radio_id": "na", "updates": {"channel": 36}},
        ),
        (
            "access_create_credential",
            {
                "credential_type": "pin",
                "credential_data": {"user_id": "u-1", "pin_code": "1234", "admin": True},
            },
            {"credential_type": "pin", "data": {"user_id": "u-1", "pin_code": "1234"}},
        ),
    ],
)
def test_model_backed_translators_filter_and_default_public_payloads(
    tool_name: str,
    args: dict,
    expected_kwargs: dict,
) -> None:
    positional, kwargs = DISPATCH_ARG_TRANSLATORS[tool_name](args)
    assert positional == ()
    assert kwargs == expected_kwargs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "args"),
    [
        ("protect_get_snapshot", {"camera_id": "camera-1", "include_image": "false"}),
        ("protect_recent_events", {"metadata_fields": "*"}),
        ("unifi_get_event_types", {"unexpected": True}),
    ],
)
async def test_catalog_input_schema_rejects_wrong_types_and_unknown_args_before_manager(
    tool_name: str,
    args: dict,
) -> None:
    entry = PRODUCTION_REGISTRY.resolve(tool_name)
    factory = MagicMock()

    with pytest.raises(ValueError, match="Invalid action arguments"):
        await dispatch_action(
            registry=PRODUCTION_REGISTRY,
            factory=factory,
            session=MagicMock(),
            tool_name=tool_name,
            controller_id="cid",
            controller_products=[entry.product],
            site="default",
            args=args,
            confirm=False,
        )

    factory.get_domain_manager.assert_not_called()


@pytest.mark.asyncio
async def test_semantic_translator_rejects_physical_mutation_before_manager() -> None:
    entry = PRODUCTION_REGISTRY.resolve("protect_ptz_move")
    factory = MagicMock()

    with pytest.raises(ValueError, match="less than or equal to 1000"):
        await dispatch_action(
            registry=PRODUCTION_REGISTRY,
            factory=factory,
            session=MagicMock(),
            tool_name=entry.name,
            controller_id="cid",
            controller_products=[entry.product],
            site="default",
            args={"camera_id": "camera-1", "pan": 1000.9},
            confirm=True,
        )

    factory.get_domain_manager.assert_not_called()


@pytest.mark.parametrize(
    ("tool_name", "args", "message"),
    [
        (
            "unifi_create_network",
            {"network_data": {"name": "Guest", "purpose": "guest"}},
            "Internal firewall zone",
        ),
        (
            "unifi_update_network",
            {"network_id": "net-1", "update_data": {"purpose": "guest"}},
            "Internal firewall zone",
        ),
        (
            "unifi_update_network",
            {"network_id": "net-1", "update_data": {"_id": "controller-owned"}},
            "read-only",
        ),
        (
            "unifi_update_network",
            {"network_id": "net-1", "update_data": {"unknown": True}},
            "Unknown network field",
        ),
        (
            "unifi_update_network",
            {"network_id": "net-1", "update_data": {"enabled": "not-a-boolean"}},
            "Invalid network update data",
        ),
        ("unifi_update_network", {"network_id": "net-1", "update_data": {}}, "update_data cannot be empty"),
        (
            "unifi_create_network",
            {"network_data": {"name": "Broken", "purpose": "unsupported", "ip_subnet": "10.0.0.1/24"}},
            "Invalid 'purpose'",
        ),
        (
            "unifi_update_wlan",
            {"wlan_id": "wlan-1", "update_data": {"enabled": False, "unknown": True}},
            "Unknown WLAN field",
        ),
        (
            "unifi_create_wlan",
            {"wlan_data": {"name": "SSID", "security": "wpa2-psk", "unknown": True}},
            "Unknown WLAN field",
        ),
        ("unifi_update_gateway_settings", {"update_data": {}}, "update_data cannot be empty"),
        (
            "unifi_update_gateway_settings",
            {"update_data": {"_id": "read-only", "unknown": True}},
            "No valid mutable fields",
        ),
        (
            "access_create_credential",
            {"credential_type": "pin", "credential_data": {}},
            "No credential data provided",
        ),
        (
            "unifi_set_client_ip_settings",
            {"mac_address": "aa:bb:cc:dd:ee:ff"},
            "At least one setting must be provided",
        ),
        (
            "unifi_update_device_radio",
            {"mac_address": "aa:bb:cc:dd:ee:ff", "radio": "na", "tx_power": 20},
            "tx_power can only be set",
        ),
        (
            "unifi_update_device_radio",
            {"mac_address": "aa:bb:cc:dd:ee:ff", "radio": "invalid", "channel": 36},
            "Invalid radio",
        ),
        (
            "unifi_set_device_led",
            {"device_mac": "aa:bb:cc:dd:ee:ff", "led_state": "blink"},
            "Invalid led_state",
        ),
        (
            "unifi_authorize_guest",
            {"mac_address": "aa:bb:cc:dd:ee:ff", "minutes": 0},
            "greater than or equal to 1",
        ),
        (
            "unifi_create_route",
            {"name": " ", "network": "not-cidr", "nexthop": "not-ip", "distance": 0},
            "Name is required",
        ),
        (
            "unifi_update_route",
            {"route_id": "route-1"},
            "At least one field must be provided",
        ),
        (
            "access_unlock_door",
            {"door_id": "door-1", "duration": 0},
            "greater than or equal to 1",
        ),
        (
            "protect_ptz_preset",
            {"camera_id": "camera-1", "preset_slot": -1},
            "greater than or equal to 0",
        ),
        (
            "protect_export_clip",
            {
                "camera_id": "camera-1",
                "start": "2026-01-01T00:00:00Z",
                "end": "2026-01-01T00:01:00Z",
                "channel_index": 3,
            },
            "less than or equal to 2",
        ),
        (
            "protect_trigger_chime",
            {"chime_id": "chime-1", "volume": 101},
            "less than or equal to 100",
        ),
        (
            "protect_ptz_move",
            {"camera_id": "camera-1", "pan": 1000.9},
            "less than or equal to 1000",
        ),
        (
            "protect_toggle_rtsp",
            {"camera_id": "camera-1", "enabled": True, "quality": "HIGH"},
            "Input should be",
        ),
        (
            "protect_alarm_update_rule",
            {"rule_id": "rule-1", "fields": {}},
            "No fields provided",
        ),
        (
            "protect_alarm_create_rule",
            {"body": {"title": "Broken", "actions": []}},
            "actions must be a non-empty list",
        ),
    ],
)
def test_semantic_translators_reject_payloads_the_mcp_wrapper_rejects(
    tool_name: str,
    args: dict,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        DISPATCH_ARG_TRANSLATORS[tool_name](args)


def test_wlan_update_translator_includes_minrate_dependencies() -> None:
    positional, kwargs = DISPATCH_ARG_TRANSLATORS["unifi_update_wlan"](
        {"wlan_id": "wlan-1", "update_data": {"minrate_ng_data_rate_kbps": 6000}}
    )

    assert positional == ()
    assert kwargs == {
        "wlan_id": "wlan-1",
        "update_data": {
            "minrate_ng_data_rate_kbps": 6000,
            "minrate_ng_enabled": True,
            "minrate_setting_preference": "manual",
        },
    }


@pytest.mark.asyncio
async def test_wlan_update_preview_uses_effective_translated_fields() -> None:
    factory = MagicMock()

    result = await dispatch_action(
        registry=PRODUCTION_REGISTRY,
        factory=factory,
        session=MagicMock(),
        tool_name="unifi_update_wlan",
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args={"wlan_id": "wlan-1", "update_data": {"minrate_ng_data_rate_kbps": 6000}},
        confirm=False,
    )

    assert isinstance(result, MutationPreview)
    assert result.payload["preview"]["proposed"]["update_data"] == {
        "minrate_ng_data_rate_kbps": 6000,
        "minrate_ng_enabled": True,
        "minrate_setting_preference": "manual",
    }
    create_result = await dispatch_action(
        registry=PRODUCTION_REGISTRY,
        factory=factory,
        session=MagicMock(),
        tool_name="unifi_create_wlan",
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args={"wlan_data": {"name": "Preview SSID", "security": "open"}},
        confirm=False,
    )

    assert isinstance(create_result, MutationPreview)
    assert create_result.payload["preview"]["will_create"]["wlan_data"]["enabled"] is True
    factory.get_domain_manager.assert_not_called()


@pytest.mark.asyncio
async def test_port_forward_preview_uses_effective_translated_payload_and_rejects_typos() -> None:
    factory = MagicMock()
    args = {
        "port_forward_data": {
            "name": "Web",
            "dst_port": "443",
            "fwd_port": "8443",
            "fwd_ip": "192.168.1.10",
        }
    }

    result = await dispatch_action(
        registry=PRODUCTION_REGISTRY,
        factory=factory,
        session=MagicMock(),
        tool_name="unifi_create_port_forward",
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args=args,
        confirm=False,
    )

    preview = result.payload["preview"]["will_create"]["port_forward_data"]
    assert preview["enabled"] is True
    assert preview["proto"] == "tcp/udp"
    assert preview["dst_port"] == "443"

    typo_args = {"port_forward_data": {**args["port_forward_data"], "enable": False}}
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        await dispatch_action(
            registry=PRODUCTION_REGISTRY,
            factory=factory,
            session=MagicMock(),
            tool_name="unifi_create_port_forward",
            controller_id="cid",
            controller_products=["network"],
            site="default",
            args=typo_args,
            confirm=False,
        )

    factory.get_domain_manager.assert_not_called()


def test_network_translators_validate_types_and_normalize_vlan() -> None:
    positional, kwargs = DISPATCH_ARG_TRANSLATORS["unifi_create_network"](
        {"network_data": {"name": "Lab", "purpose": "vlan-only", "vlan": 4092, "enabled": False}}
    )

    assert positional == ()
    assert kwargs == {
        "network_data": {
            "name": "Lab",
            "purpose": "vlan-only",
            "vlan": 4092,
            "enabled": False,
        }
    }


@pytest.mark.parametrize("limit", [None, 0, -1])
def test_access_list_users_normalizes_nonpositive_or_omitted_limit(limit: int | None) -> None:
    args = {} if limit is None else {"limit": limit}

    positional, kwargs = DISPATCH_ARG_TRANSLATORS["access_list_users"](args)

    assert positional == ()
    assert kwargs == {"page_size": 25}


def test_simple_port_forward_matches_wrapper_empty_port_and_unknown_protocol_fallback() -> None:
    positional, kwargs = DISPATCH_ARG_TRANSLATORS["unifi_create_simple_port_forward"](
        {
            "rule": {
                "name": "Odd but wrapper-compatible",
                "ext_port": "8443",
                "int_port": "",
                "to_ip": "192.168.1.20",
                "protocol": "unexpected",
            }
        }
    )

    assert positional == ()
    assert kwargs["rule_data"]["fwd_port"] == ""
    assert kwargs["rule_data"]["proto"] == "tcp/udp"


def test_omitted_public_defaults_are_injected_before_required_manager_calls() -> None:
    _, detection_kwargs = DISPATCH_ARG_TRANSLATORS["protect_search_detections"]({"labels": ["color:black"]})
    assert detection_kwargs == {
        "labels": ["color:black"],
        "limit": 100,
        "order": "desc",
        "exclude_motion": True,
        "min_confidence": None,
        "start": None,
        "end": None,
    }

    _, voucher_kwargs = DISPATCH_ARG_TRANSLATORS["unifi_create_voucher"]({})
    assert voucher_kwargs["expire_minutes"] == 1440
    assert voucher_kwargs["count"] == 1
    assert voucher_kwargs["quota"] == 1


def test_top_clients_unknown_duration_matches_wrapper_one_hour_fallback() -> None:
    _, kwargs = DISPATCH_ARG_TRANSLATORS["unifi_get_top_clients"]({"duration": "typo"})
    assert kwargs == {"duration_hours": 1, "limit": 10}


def test_alarm_facade_result_adapter_unwraps_result_and_preserves_coverage() -> None:
    adapter = DISPATCH_RESULT_ADAPTERS["protect_alarm_create_rule"]

    complete = adapter(({"id": "rule-1"}, True), {}, MagicMock())
    fallback = adapter(({"id": "rule-2"}, False), {}, MagicMock())

    assert complete == {"id": "rule-1"}
    assert fallback["id"] == "rule-2"
    assert fallback["_meta"]["com.github.sirkirby.unifi-mcp/alarm-coverage"]["complete"] is False


def test_delete_recording_result_adapter_rejects_unsupported_operation() -> None:
    adapter = DISPATCH_RESULT_ADAPTERS["protect_delete_recording"]

    with pytest.raises(ValueError, match="not supported"):
        adapter(
            {"supported": False, "message": "Individual recording deletion is not supported"},
            {},
            MagicMock(),
        )


def test_create_port_profile_translator_sends_defaults_that_keep_poe_on() -> None:
    """Packing only the supplied keys is not equivalent for this tool.

    poe_mode, stp_port_mode and isolation must reach the controller even when
    the caller takes the documented default, or the controller applies its own —
    for poe_mode that creates the profile with PoE off, de-energising anything
    wired through a port using it.
    """
    translator = DISPATCH_ARG_TRANSLATORS["unifi_create_port_profile"]

    _, kwargs = translator({"name": "Access", "forward": "native", "tagged_vlan_mgmt": "block_all"})

    payload = kwargs["profile_data"]
    assert payload["poe_mode"] == "auto"
    assert payload["stp_port_mode"] is True
    assert payload["isolation"] is False
    assert payload["tagged_vlan_mgmt"] == "block_all"


def test_create_port_profile_translator_forwards_new_access_port_fields() -> None:
    translator = DISPATCH_ARG_TRANSLATORS["unifi_create_port_profile"]

    _, kwargs = translator(
        {
            "name": "Access",
            "forward": "native",
            "tagged_vlan_mgmt": "block_all",
            "excluded_networkconf_ids": ["net-9"],
            "stp_edge_state": "enabled",
            "stp_bpdu_guard_enabled": True,
            "stp_uplink": False,
        }
    )

    payload = kwargs["profile_data"]
    assert payload["excluded_networkconf_ids"] == ["net-9"]
    assert payload["stp_edge_state"] == "enabled"
    assert payload["stp_bpdu_guard_enabled"] is True
    assert payload["stp_uplink"] is False


def test_create_port_profile_translator_forwards_all_storm_control_fields() -> None:
    translator = DISPATCH_ARG_TRANSLATORS["unifi_create_port_profile"]

    _, kwargs = translator(
        {
            "name": "Storm",
            "forward": "native",
            "stormctrl_bcast_enabled": True,
            "stormctrl_bcast_rate": 500,
            "stormctrl_mcast_enabled": False,
            "stormctrl_mcast_rate": 1000,
            "stormctrl_ucast_enabled": True,
            "stormctrl_ucast_rate": 1500,
        }
    )

    assert kwargs["profile_data"] == {
        "name": "Storm",
        "forward": "native",
        "isolation": False,
        "poe_mode": "auto",
        "stp_port_mode": True,
        "stormctrl_bcast_enabled": True,
        "stormctrl_bcast_rate": 500,
        "stormctrl_mcast_enabled": False,
        "stormctrl_mcast_rate": 1000,
        "stormctrl_ucast_enabled": True,
        "stormctrl_ucast_rate": 1500,
    }


def test_create_port_profile_translator_requires_name_and_forward() -> None:
    translator = DISPATCH_ARG_TRANSLATORS["unifi_create_port_profile"]

    with pytest.raises(ValueError):
        translator({"name": "Access"})
