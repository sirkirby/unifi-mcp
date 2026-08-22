"""Access device lookups accept a MAC in either case, and resolve it.

`device_id` here may be either an opaque `unique_id` or a MAC. Only the MAC
arm is case-insensitive: unique_ids are not addresses, so relaxing their
comparison would be a guess rather than a fix.

Resolving matters as much as matching. The reboot path interpolates its
argument straight into the request path, so a lookup that starts accepting
a MAC must hand the controller the identifier the controller actually
indexes by, not the string the caller happened to type.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.access.managers.device_manager import DeviceManager

LOWER = "aa:bb:cc:dd:ee:ff"
UPPER = "AA:BB:CC:DD:EE:FF"
UNIQUE_ID = "0123456789abcdef01234567"
OTHER_ID = "fedcba9876543210fedcba98"
OTHER_MAC = "11:22:33:44:55:66"

# topology4 nests devices as site -> floors -> doors -> device_groups -> devices
TOPOLOGY = {
    "data": [
        {
            "floors": [
                {
                    "doors": [
                        {
                            "name": "Entry",
                            "unique_id": "door-1",
                            "device_groups": [
                                [
                                    {"unique_id": UNIQUE_ID, "mac": LOWER, "name": "Entry Reader", "type": "UA-G2"},
                                    {"unique_id": OTHER_ID, "mac": OTHER_MAC, "name": "Side Reader", "type": "UA-G2"},
                                ]
                            ],
                        }
                    ]
                }
            ]
        }
    ]
}


def _manager() -> DeviceManager:
    cm = MagicMock()
    cm.has_api_client = False  # force the proxy path, which is the one that matches on MAC
    cm.has_proxy = True
    cm.proxy_request = AsyncMock(return_value=TOPOLOGY)
    cm.extract_data = MagicMock(side_effect=lambda d: d.get("data", []))
    return DeviceManager(cm)


@pytest.mark.asyncio
async def test_get_device_accepts_an_uppercase_mac() -> None:
    mgr = _manager()
    assert (await mgr.get_device(UPPER))["name"] == "Entry Reader"


@pytest.mark.asyncio
async def test_get_device_still_matches_a_unique_id_exactly() -> None:
    """With two devices present, a match-anything predicate returns the wrong
    one - which a single-device fixture could never detect."""
    mgr = _manager()
    assert (await mgr.get_device(OTHER_ID))["name"] == "Side Reader"
    assert (await mgr.get_device(UNIQUE_ID))["name"] == "Entry Reader"


@pytest.mark.asyncio
async def test_get_device_raises_for_an_unknown_identifier() -> None:
    from unifi_core.exceptions import UniFiNotFoundError

    mgr = _manager()
    with pytest.raises(UniFiNotFoundError):
        await mgr.get_device("99:99:99:99:99:99")


@pytest.mark.asyncio
async def test_reboot_preview_resolves_a_mac_to_the_unique_id() -> None:
    """The preview's device_id is what the confirm step sends to the URL."""
    mgr = _manager()
    assert (await mgr.reboot_device(UPPER))["device_id"] == UNIQUE_ID


@pytest.mark.asyncio
async def test_apply_reboot_posts_to_the_unique_id_not_the_callers_mac() -> None:
    mgr = _manager()
    await mgr.apply_reboot_device(UPPER)
    paths = [c.args[1] for c in mgr._cm.proxy_request.call_args_list if len(c.args) > 1]
    assert f"devices/{UNIQUE_ID}/reboot" in paths, paths
    assert not any(UPPER in p for p in paths), f"the caller's raw MAC reached the URL: {paths}"
