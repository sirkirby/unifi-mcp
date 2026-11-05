"""Port override writes merge into the switch's current overrides instead of replacing them."""

from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.network.managers.switch_manager import SwitchManager

SWITCH_MAC = "aa:bb:cc:dd:ee:ff"
CURRENT = [
    {"port_idx": 1, "name": "uplink", "portconf_id": "trunk"},
    {"port_idx": 2, "name": "printer", "portconf_id": "office", "poe_mode": "off"},
    # A LAG member keeps its own entry while aggregated; the merge must not drop it.
    {"port_idx": 7, "op_mode": "aggregate", "aggregate_num_ports": 2},
]


def _manager(overrides: list[dict] | None = None):
    device = {"_id": "dev1", "mac": SWITCH_MAC}
    if overrides is not None:
        device["port_overrides"] = deepcopy(overrides)
    conn = MagicMock()
    conn.ensure_connected = AsyncMock(return_value=True)
    puts: list[dict] = []

    async def request(api_request):
        if api_request.method == "get":
            return [deepcopy(device)]
        puts.append(deepcopy(api_request.data))
        return {}

    conn.request = AsyncMock(side_effect=request)
    return SwitchManager(conn), puts


@pytest.mark.asyncio
async def test_changing_one_port_keeps_every_other_override():
    manager, puts = _manager(CURRENT)

    assert await manager.set_port_overrides(SWITCH_MAC, [{"port_idx": 2, "portconf_id": "cameras"}]) is True

    assert puts == [
        {
            "port_overrides": [
                CURRENT[0],
                {"port_idx": 2, "portconf_id": "cameras"},
                CURRENT[2],
            ]
        }
    ]


@pytest.mark.asyncio
async def test_a_new_port_is_added_and_the_full_array_is_unchanged_by_resending_it():
    manager, puts = _manager(CURRENT)

    await manager.set_port_overrides(SWITCH_MAC, [*deepcopy(CURRENT), {"port_idx": 4, "portconf_id": "iot"}])

    assert puts[0]["port_overrides"] == [*CURRENT, {"port_idx": 4, "portconf_id": "iot"}]


@pytest.mark.asyncio
async def test_a_switch_without_overrides_gets_only_the_sent_entries():
    manager, puts = _manager(None)

    await manager.set_port_overrides(SWITCH_MAC, [{"port_idx": 3, "portconf_id": "iot"}])

    assert puts[0]["port_overrides"] == [{"port_idx": 3, "portconf_id": "iot"}]


@pytest.mark.asyncio
async def test_an_override_is_removed_only_when_asked():
    manager, puts = _manager(CURRENT)

    await manager.set_port_overrides(SWITCH_MAC, [], remove_port_idxs=[2])

    assert puts[0]["port_overrides"] == [CURRENT[0], CURRENT[2]]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "remove", "message"),
    [
        ([{"portconf_id": "x"}], None, "port_idx"),
        ([{"port_idx": "2", "portconf_id": "x"}], None, "port_idx"),
        ([{"port_idx": True, "portconf_id": "x"}], None, "port_idx"),
        ([{"port_idx": 2}, {"port_idx": 2}], None, "more than once"),
        ([{"port_idx": 2}], [2], "both"),
        ([], [5], "no override"),
        ([], None, "No port override changes"),
    ],
)
async def test_ambiguous_or_empty_changes_are_refused_before_any_write(overrides, remove, message):
    manager, puts = _manager(CURRENT)

    with pytest.raises(ValueError, match=message):
        await manager.set_port_overrides(SWITCH_MAC, overrides, remove_port_idxs=remove)
    assert puts == []


@pytest.mark.asyncio
async def test_the_plan_names_changed_added_and_removed_ports_without_writing():
    manager, puts = _manager(CURRENT)

    plan = await manager.plan_port_overrides(
        SWITCH_MAC, [{"port_idx": 2, "portconf_id": "cameras"}, {"port_idx": 4}], remove_port_idxs=[7]
    )

    assert plan["current"] == CURRENT
    assert plan["merged"] == [CURRENT[0], {"port_idx": 2, "portconf_id": "cameras"}, {"port_idx": 4}]
    assert (plan["changed_ports"], plan["added_ports"], plan["removed_ports"]) == ([2], [4], [7])
    assert plan["kept_ports"] == [1]
    assert puts == []


@pytest.mark.asyncio
async def test_overlapping_writes_to_one_switch_keep_both_changes():
    import asyncio

    device = {"_id": "dev1", "mac": SWITCH_MAC, "port_overrides": deepcopy(CURRENT)}
    conn = MagicMock()
    conn.ensure_connected = AsyncMock(return_value=True)

    async def request(api_request):
        if api_request.method == "get":
            snapshot = [deepcopy(device)]
            await asyncio.sleep(0.01)  # let the other write read the same state if nothing serializes them
            return snapshot
        await asyncio.sleep(0.01)
        device["port_overrides"] = deepcopy(api_request.data["port_overrides"])
        return {}

    conn.request = AsyncMock(side_effect=request)
    manager = SwitchManager(conn)

    # The same switch spelled two ways must share one lock.
    await asyncio.gather(
        manager.set_port_overrides(SWITCH_MAC, [{"port_idx": 1, "portconf_id": "a"}]),
        manager.set_port_overrides(SWITCH_MAC.replace(":", "").upper(), [{"port_idx": 2, "portconf_id": "b"}]),
    )

    ports = {entry["port_idx"]: entry for entry in device["port_overrides"]}
    assert ports[1] == {"port_idx": 1, "portconf_id": "a"}
    assert ports[2] == {"port_idx": 2, "portconf_id": "b"}
    assert ports[7] == CURRENT[2]
