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
from unifi_core.redaction import REDACTED


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
            "unifi_list_clients": DispatchEntry(manager_attr="client_manager", method="get_clients"),
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
            "unifi_list_clients": DispatchEntry(manager_attr="client_manager", method="get_clients"),
        },
    )

    conn_manager.set_site.assert_awaited_once_with("upstairs")
    # The list_clients translator strips filter kwargs; get_clients() takes no args.
    domain_manager.get_clients.assert_awaited_once_with()


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
    assert table["unifi_get_device_stats"].method == "get_device_stats"
    assert table["unifi_get_client_stats"].method == "get_client_stats"

    # Protect preview/execute split
    assert table["protect_reboot_camera"].method == "apply_reboot_camera"
    assert table["protect_alarm_arm"].method == "arm"
    assert table["protect_acknowledge_event"].method == "apply_acknowledge_event"
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
    )
    # The widened match field is forwarded to update_traffic_route as a kwarg
    # (no arg translator — the manager takes **kwargs; confirm is a separate arg).
    domain_manager.update_traffic_route.assert_awaited_once_with(route_id="tr1", target_devices=target_devices)


@pytest.mark.asyncio
async def test_dispatch_reorder_firewall_policies_requires_confirm() -> None:
    entry = ToolEntry(
        name="unifi_reorder_firewall_policies",
        product="network",
        category="firewall",
        manager="",
        method="",
    )
    registry = _registry_with(entry)
    factory = MagicMock()

    with pytest.raises(ValueError, match="requires confirm=true"):
        await dispatch_action(
            registry=registry,
            factory=factory,
            session=MagicMock(),
            tool_name="unifi_reorder_firewall_policies",
            controller_id="cid",
            controller_products=["network"],
            site="default",
            args={
                "source_firewall_zone_id": "zone-src",
                "destination_firewall_zone_id": "zone-dst",
                "ordered_firewall_policy_ids": {
                    "beforeSystemDefined": ["allow-1"],
                    "afterSystemDefined": ["block-1"],
                },
            },
            confirm=False,
            dispatch_table={
                "unifi_reorder_firewall_policies": DispatchEntry(
                    manager_attr="firewall_manager",
                    method="reorder_firewall_policies",
                ),
            },
        )

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
        args={"update_data": {"upnp_enabled": True, "_id": "x", "key": "usg", "bogus": 1}},
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
    assert positional[0] == {"upnp_enabled": True}


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
# Network — list_clients: manager get_clients() takes no arguments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_translates_list_clients_strips_filter_kwargs() -> None:
    """unifi_list_clients: filter_type/include_offline/limit are tool-only;
    get_clients() accepts no arguments."""
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
        site="default",
        args={"filter_type": "wireless", "include_offline": False, "limit": 50},
        confirm=False,
        dispatch_table={
            "unifi_list_clients": DispatchEntry(manager_attr="client_manager", method="get_clients"),
        },
    )

    domain_manager.get_clients.assert_awaited_once_with()


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
