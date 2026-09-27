"""API actions accept the public MAC spelling and preserve Core manager kwargs."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_api.services.actions import dispatch_action
from unifi_api.services.dispatch_overrides import DISPATCH_ARG_TRANSLATORS
from unifi_api.services.manifest import ManifestRegistry, ToolEntry

MAC = "aa:bb:cc:dd:ee:ff"
DEVICE_TOOLS = (
    "unifi_configure_port_aggregation",
    "unifi_configure_port_mirror",
    "unifi_force_provision_device",
    "unifi_get_lldp_neighbors",
    "unifi_get_port_stats",
    "unifi_get_switch_capabilities",
    "unifi_get_switch_ports",
    "unifi_locate_device",
    "unifi_power_cycle_port",
    "unifi_set_device_led",
    "unifi_set_jumbo_frames",
    "unifi_set_switch_port_profile",
    "unifi_toggle_device",
    "unifi_update_switch_stp",
)
CLIENT_TOOLS = ("unifi_get_client_dpi_traffic", "unifi_get_client_sessions", "unifi_get_client_wifi_details")
EXTRAS = {
    "unifi_configure_port_aggregation": {"port_overrides": []},
    "unifi_configure_port_mirror": {"port_overrides": []},
    "unifi_locate_device": {"enabled": True},
    "unifi_power_cycle_port": {"port_idx": 1},
    "unifi_set_device_led": {"led_state": "on"},
    "unifi_set_jumbo_frames": {"enabled": True},
    "unifi_set_switch_port_profile": {"port_overrides": []},
    "unifi_toggle_device": {"disabled": True},
    "unifi_update_switch_stp": {"stp_priority": 32768},
    "unifi_get_client_dpi_traffic": {"group_by": "by_cat"},
    "unifi_get_client_sessions": {"duration": "weekly", "limit": 9},
    "unifi_recent_events": {"event_type": "EVT", "limit": 9},
}


@pytest.mark.parametrize("tool", [*DEVICE_TOOLS, *CLIENT_TOOLS, "unifi_recent_events"])
def test_all_migrated_actions_translate_public_mac_to_manager_keyword(tool: str) -> None:
    translator = DISPATCH_ARG_TRANSLATORS[tool]
    positional, keyword = translator({"mac_address": MAC, **EXTRAS.get(tool, {})})
    expected_key = "device_mac" if tool in DEVICE_TOOLS else "mac" if tool == "unifi_recent_events" else "client_mac"
    assert positional == ()
    assert keyword[expected_key] == MAC
    assert "mac_address" not in keyword
    assert set(keyword) == translator.manager_parameters


@pytest.mark.parametrize("tool", ["unifi_get_client_sessions", "unifi_recent_events"])
def test_optional_mac_omission_stays_optional(tool: str) -> None:
    positional, keyword = DISPATCH_ARG_TRANSLATORS[tool]({})
    assert positional == ()
    assert not {"mac_address", "client_mac", "mac"} & keyword.keys()


def _registry(tool: str, method: str, *, mutation: bool = False) -> ManifestRegistry:
    return ManifestRegistry(
        {
            tool: ToolEntry(
                name=tool,
                product="network",
                category="switch",
                manager="switch_manager",
                method=method,
                read_only_hint=not mutation,
                permission_action="update" if mutation else "",
                input_schema={
                    "type": "object",
                    "properties": {"mac_address": {"type": "string"}, "led_state": {"type": "string"}},
                    "additionalProperties": False,
                },
            )
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "method", "extra", "expected"),
    [
        ("unifi_get_switch_ports", "get_switch_ports", {}, {"device_mac": MAC}),
        (
            "unifi_set_device_led",
            "set_device_led_override",
            {"led_state": "on"},
            {"device_mac": MAC, "led_override": "on"},
        ),
    ],
)
async def test_dispatch_uses_new_name_and_rejects_old_name(tool, method, extra, expected) -> None:
    manager = MagicMock()
    setattr(manager, method, AsyncMock(return_value={"ok": True}))
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)
    common = dict(
        registry=_registry(tool, method, mutation=bool(extra)),
        factory=factory,
        session=MagicMock(),
        tool_name=tool,
        controller_id="cid",
        controller_products=["network"],
        site="default",
        confirm=True,
    )
    assert await dispatch_action(args={"mac_address": MAC, **extra}, **common) == {"ok": True}
    getattr(manager, method).assert_awaited_once_with(**expected)
    factory.get_domain_manager.reset_mock()
    old = "device_mac"
    with pytest.raises(ValueError, match=f"unknown argument\\(s\\) {old}"):
        await dispatch_action(args={old: MAC, **extra}, **common)
    factory.get_domain_manager.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "method", "manager_key", "old"),
    [
        ("unifi_get_client_sessions", "get_client_sessions", "client_mac", "client_mac"),
        ("unifi_recent_events", "get_recent_from_buffer", "mac", "mac"),
    ],
)
async def test_optional_action_mac_filter_keeps_omitted_and_explicit_behavior(tool, method, manager_key, old) -> None:
    manager = MagicMock()
    # The event buffer is synchronous; sessions require controller I/O.
    method_mock = MagicMock(return_value=[]) if method == "get_recent_from_buffer" else AsyncMock(return_value=[])
    setattr(manager, method, method_mock)
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)
    common = dict(
        registry=_registry(tool, method),
        factory=factory,
        session=MagicMock(),
        tool_name=tool,
        controller_id="cid",
        controller_products=["network"],
        site="default",
        confirm=False,
    )
    assert await dispatch_action(args={}, **common) == []
    assert manager_key not in method_mock.call_args.kwargs
    assert await dispatch_action(args={"mac_address": MAC}, **common) == []
    assert method_mock.call_args.kwargs[manager_key] == MAC
    with pytest.raises(ValueError, match=f"unknown argument\\(s\\) {old}"):
        await dispatch_action(args={old: MAC}, **common)
