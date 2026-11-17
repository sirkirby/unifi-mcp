"""API action path for AP outdoor mode and radio antenna selection."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_api.serializers.network.devices import DeviceMutationAckSerializer
from unifi_api.services.actions import MutationPreview, dispatch_action
from unifi_api.services.dispatch_overrides import DISPATCH_ARG_TRANSLATORS, DISPATCH_OVERRIDES
from unifi_api.services.manifest import ManifestRegistry, ToolEntry

MAC = "aa:bb:cc:00:00:01"


def test_outdoor_mode_binds_to_the_write_not_the_preview_read():
    assert DISPATCH_OVERRIDES["unifi_set_device_outdoor_mode"] == ("device_manager", "set_device_outdoor_mode")
    assert DeviceMutationAckSerializer().serialize(True) == {"success": True}


def test_outdoor_mode_translator_validates_and_renames():
    translator = DISPATCH_ARG_TRANSLATORS["unifi_set_device_outdoor_mode"]

    assert translator({"mac_address": MAC, "mode": "on"}) == ((), {"device_mac": MAC, "mode": "on"})
    assert translator.manager_parameters == {"device_mac", "mode"}


def test_radio_translator_carries_antenna_id():
    translator = DISPATCH_ARG_TRANSLATORS["unifi_update_device_radio"]

    assert translator({"mac_address": MAC, "radio": "na", "antenna_id": 2}) == (
        (),
        {"device_mac": MAC, "radio_id": "na", "updates": {"antenna_id": 2}},
    )


@pytest.mark.asyncio
async def test_outdoor_mode_action_previews_without_io_and_confirms_through_core():
    entry = ToolEntry(
        name="unifi_set_device_outdoor_mode",
        product="network",
        category="devices",
        manager="device_manager",
        method="set_device_outdoor_mode",
        permission_action="update",
        read_only_hint=False,
    )
    manager = MagicMock()
    manager.set_device_outdoor_mode = AsyncMock(return_value=True)
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
        args={"mac_address": MAC, "mode": "off"},
    )

    preview = await dispatch_action(**common, confirm=False)
    assert isinstance(preview, MutationPreview)
    factory.get_domain_manager.assert_not_awaited()

    assert await dispatch_action(**common, confirm=True) is True
    manager.set_device_outdoor_mode.assert_awaited_once_with(device_mac=MAC, mode="off")

    for confirm in (False, True):
        with pytest.raises(ValueError) as exc:
            await dispatch_action(**{**common, "args": {"mac_address": MAC, "mode": "outdoor"}}, confirm=confirm)
        assert "outdoor'" not in str(exc.value)
    assert manager.set_device_outdoor_mode.await_count == 1
