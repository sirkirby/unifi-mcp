"""API action path for device IP settings."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_api.services.actions import MutationPreview, dispatch_action
from unifi_api.services.dispatch_overrides import DISPATCH_ARG_TRANSLATORS, DISPATCH_OVERRIDES
from unifi_api.services.manifest import ManifestRegistry, ToolEntry

MAC = "aa:bb:cc:00:00:01"


def test_ip_settings_binds_to_the_write_not_the_preview_read():
    assert DISPATCH_OVERRIDES["unifi_set_device_ip_settings"] == ("device_manager", "set_device_ip_settings")


def test_ip_settings_translator_validates_renames_and_passes_given_fields_only():
    translator = DISPATCH_ARG_TRANSLATORS["unifi_set_device_ip_settings"]

    assert translator({"mac_address": MAC, "mode": "static", "dns2": "198.51.100.53", "ip": None}) == (
        (),
        {"device_mac": MAC, "mode": "static", "dns2": "198.51.100.53"},
    )
    assert translator.manager_parameters == {"device_mac", "mode", "ip", "netmask", "gateway", "dns1", "dns2"}


@pytest.mark.asyncio
async def test_ip_settings_action_previews_without_io_and_confirms_through_core():
    entry = ToolEntry(
        name="unifi_set_device_ip_settings",
        product="network",
        category="devices",
        manager="device_manager",
        method="set_device_ip_settings",
        permission_action="update",
        read_only_hint=False,
    )
    manager = MagicMock()
    manager.set_device_ip_settings = AsyncMock(return_value=True)
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)
    common = dict(
        registry=ManifestRegistry({entry.name: entry}),
        factory=factory,
        session=MagicMock(),
        tool_name=entry.name,
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args={"mac_address": MAC, "mode": "dhcp"},
    )

    preview = await dispatch_action(**common, confirm=False)
    assert isinstance(preview, MutationPreview)
    factory.get_domain_manager.assert_not_awaited()

    assert await dispatch_action(**common, confirm=True) is True
    manager.set_device_ip_settings.assert_awaited_once_with(device_mac=MAC, mode="dhcp")

    for confirm in (False, True):
        with pytest.raises(ValueError):
            await dispatch_action(**{**common, "args": {"mac_address": MAC, "mode": "manual"}}, confirm=confirm)
    assert manager.set_device_ip_settings.await_count == 1
