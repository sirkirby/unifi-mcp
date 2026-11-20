"""Firewall policy order through the V2 API: reading a zone pair's order and batch-reorder."""

import asyncio
import copy
from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.exceptions import UniFiNotFoundError, UniFiOperationError
from unifi_core.network.managers.firewall_manager import FirewallManager

SRC = "zone-src"
DST = "zone-dst"
ZONES = [
    {"_id": SRC, "name": "Internal", "external_id": "integration-src"},
    {"_id": DST, "name": "External", "external_id": "integration-dst"},
]
ZONE_READ = ("get", "/firewall/zone")
POLICY_READ = ("get", "/firewall-policies")
REORDER = ("put", "/firewall-policies/batch-reorder")


def _policy(policy_id, index, src=SRC, dst=DST, predefined=False):
    return {
        "_id": policy_id,
        "name": policy_id,
        "index": index,
        "predefined": predefined,
        "source": {"zone_id": src},
        "destination": {"zone_id": dst},
    }


def _policies():
    return [
        _policy("user-b", 10001),
        _policy("predefined-2", 2147483647, predefined=True),
        _policy("user-a", 10000),
        _policy("predefined-1", 30000, predefined=True),
        _policy("user-c", 40000),
        _policy("reverse-pair", 10000, src=DST, dst=SRC),
    ]


class FakeController:
    """Answers the V2 zone and policy reads and applies batch-reorder to the policy indexes."""

    def __init__(self, policies=None, apply_reorders=True):
        self.policies = _policies() if policies is None else policies
        self.apply_reorders = apply_reorders
        self.calls = []
        self.reorders = []

    async def request(self, api_request):
        self.calls.append((api_request.method, api_request.path))
        if api_request.path == "/firewall/zone":
            return copy.deepcopy(ZONES)
        if api_request.method == "get":
            return copy.deepcopy(self.policies)
        self.reorders.append(copy.deepcopy(api_request.data))
        if self.apply_reorders:
            self._apply(api_request.data)
        return []

    def _apply(self, data):
        indexes = {policy_id: 10000 + offset for offset, policy_id in enumerate(data["before_predefined_ids"])}
        indexes.update({policy_id: 40000 + offset for offset, policy_id in enumerate(data["after_predefined_ids"])})
        for policy in self.policies:
            if policy["_id"] in indexes:
                policy["index"] = indexes[policy["_id"]]


def _manager(controller):
    connection = MagicMock()
    connection.site = "default"
    connection.ensure_connected = AsyncMock(return_value=True)
    connection.request = AsyncMock(side_effect=controller.request)
    connection.get_cached = MagicMock(return_value=None)
    connection._update_cache = MagicMock()
    connection._invalidate_cache = MagicMock()
    return FirewallManager(connection), connection


# --- reading the order ------------------------------------------------------------


@pytest.mark.asyncio
async def test_order_splits_user_policies_at_the_system_defined_band():
    controller = FakeController()
    manager, _ = _manager(controller)

    order = await manager.get_firewall_policy_order_v2(SRC, DST)

    assert order == {"before_predefined_ids": ["user-a", "user-b"], "after_predefined_ids": ["user-c"]}
    assert controller.calls == [ZONE_READ, POLICY_READ]


@pytest.mark.asyncio
async def test_order_of_a_pair_whose_only_predefined_policy_is_the_default():
    policies = [
        _policy("default", 2147483647, predefined=True),
        _policy("user-after", 40000),
        _policy("user-before", 10000),
    ]
    manager, _ = _manager(FakeController(policies=policies))

    order = await manager.get_firewall_policy_order_v2(SRC, DST)

    assert order == {"before_predefined_ids": ["user-before"], "after_predefined_ids": ["user-after"]}


@pytest.mark.asyncio
async def test_order_without_predefined_policies_keeps_both_sides():
    controller = FakeController(policies=[_policy("user-b", 10001), _policy("user-c", 40000), _policy("user-a", 10000)])
    manager, _ = _manager(controller)

    order = await manager.get_firewall_policy_order_v2(SRC, DST)

    assert order == {"before_predefined_ids": ["user-a", "user-b"], "after_predefined_ids": ["user-c"]}


@pytest.mark.asyncio
async def test_order_reads_a_wrapped_policy_list():
    controller = FakeController()
    manager, connection = _manager(controller)

    async def wrapped(api_request):
        result = await controller.request(api_request)
        return {"data": result} if api_request.path == "/firewall-policies" else result

    connection.request.side_effect = wrapped

    order = await manager.get_firewall_policy_order_v2(SRC, DST)

    assert order == {"before_predefined_ids": ["user-a", "user-b"], "after_predefined_ids": ["user-c"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [None, {"errorCode": 404}, "unavailable"])
async def test_order_refuses_a_response_without_a_policy_list(response):
    controller = FakeController()
    manager, connection = _manager(controller)

    async def answer(api_request):
        result = await controller.request(api_request)
        return response if api_request.path == "/firewall-policies" else result

    connection.request.side_effect = answer

    with pytest.raises(UniFiOperationError, match="did not return a firewall policy list"):
        await manager.get_firewall_policy_order_v2(SRC, DST)


@pytest.mark.asyncio
@pytest.mark.parametrize("zones", [("zone-missing", DST), (SRC, "integration-dst"), ("", DST)])
async def test_order_matches_zones_by_v2_id_only(zones):
    controller = FakeController()
    manager, _ = _manager(controller)

    with pytest.raises(UniFiNotFoundError):
        await manager.get_firewall_policy_order_v2(*zones)
    assert controller.calls == [ZONE_READ]


@pytest.mark.asyncio
@pytest.mark.parametrize("index", [None, "10002", True, 10002.0])
async def test_order_refuses_a_policy_without_an_integer_index(index):
    policies = [*_policies(), _policy("user-unplaced", index)]
    manager, _ = _manager(FakeController(policies=policies))

    with pytest.raises(UniFiOperationError, match="without an index or ID: user-unplaced$"):
        await manager.get_firewall_policy_order_v2(SRC, DST)


@pytest.mark.asyncio
async def test_order_refuses_a_user_policy_without_an_id():
    unnamed = _policy("", 10002)
    unnamed["name"] = "No ID"
    manager, _ = _manager(FakeController(policies=[*_policies(), unnamed]))

    with pytest.raises(UniFiOperationError, match="without an index or ID: No ID$"):
        await manager.get_firewall_policy_order_v2(SRC, DST)


@pytest.mark.asyncio
async def test_order_ignores_unplaceable_policies_of_other_pairs():
    policies = [*_policies(), _policy("other-pair", None, src=DST, dst=DST)]
    manager, _ = _manager(FakeController(policies=policies))

    order = await manager.get_firewall_policy_order_v2(SRC, DST)

    assert order == {"before_predefined_ids": ["user-a", "user-b"], "after_predefined_ids": ["user-c"]}


# --- previewing a reorder ---------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_returns_the_current_and_requested_order_without_writing():
    controller = FakeController()
    manager, _ = _manager(controller)

    preview = await manager.preview_reorder_firewall_policies_v2(SRC, DST, ["user-c", "user-a"], ["user-b"])

    assert preview == {
        "current": {"before_predefined_ids": ["user-a", "user-b"], "after_predefined_ids": ["user-c"]},
        "requested": {"before_predefined_ids": ["user-c", "user-a"], "after_predefined_ids": ["user-b"]},
    }
    assert controller.calls == [ZONE_READ, POLICY_READ]


@pytest.mark.asyncio
async def test_preview_refuses_a_different_policy_set():
    controller = FakeController()
    manager, _ = _manager(controller)

    with pytest.raises(ValueError, match="Missing: user-c; unexpected: none"):
        await manager.preview_reorder_firewall_policies_v2(SRC, DST, ["user-a", "user-b"], [])
    assert controller.calls == [ZONE_READ, POLICY_READ]


# --- reordering -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reorder_writes_the_order_and_returns_the_read_back():
    controller = FakeController()
    manager, connection = _manager(controller)
    before = ["user-b"]
    after = ["user-c", "user-a"]

    result = await manager.reorder_firewall_policies_v2(SRC, DST, before, after)

    assert result == {"before_predefined_ids": ["user-b"], "after_predefined_ids": ["user-c", "user-a"]}
    assert controller.reorders == [
        {
            "before_predefined_ids": ["user-b"],
            "after_predefined_ids": ["user-c", "user-a"],
            "source_zone_id": SRC,
            "destination_zone_id": DST,
        }
    ]
    assert controller.calls == [ZONE_READ, POLICY_READ, REORDER, POLICY_READ]
    assert before == ["user-b"]
    assert after == ["user-c", "user-a"]
    invalidated = [call.args[0] for call in connection._invalidate_cache.call_args_list]
    assert invalidated == [
        "firewall_policies_True_default",
        "firewall_policies_False_default",
        "firewall_policy_ordering",
    ]


@pytest.mark.asyncio
async def test_reorder_of_a_pair_without_user_policies_writes_nothing():
    controller = FakeController(policies=[_policy("default", 2147483647, predefined=True)])
    manager, connection = _manager(controller)

    result = await manager.reorder_firewall_policies_v2(SRC, DST, [], [])

    assert result == {"before_predefined_ids": [], "after_predefined_ids": []}
    assert controller.calls == [ZONE_READ, POLICY_READ]
    connection._invalidate_cache.assert_not_called()


@pytest.mark.asyncio
async def test_reorder_fails_when_the_controller_keeps_the_old_order():
    controller = FakeController(apply_reorders=False)
    manager, _ = _manager(controller)

    with pytest.raises(UniFiOperationError, match="reports a different order"):
        await manager.reorder_firewall_policies_v2(SRC, DST, ["user-b", "user-a"], ["user-c"])
    assert controller.calls == [ZONE_READ, POLICY_READ, REORDER, POLICY_READ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("before", "after", "message"),
    [
        (["user-a", "user-b"], [], "Missing: user-c; unexpected: none"),
        (["user-a", "user-b"], ["user-c", "user-d"], "Missing: none; unexpected: user-d"),
        (["user-a", "reverse-pair"], ["user-c"], "Missing: user-b; unexpected: reverse-pair"),
    ],
)
async def test_reorder_refuses_a_different_policy_set_before_writing(before, after, message):
    controller = FakeController()
    manager, _ = _manager(controller)

    with pytest.raises(ValueError, match=message):
        await manager.reorder_firewall_policies_v2(SRC, DST, before, after)
    assert controller.calls == [ZONE_READ, POLICY_READ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("before", "after", "message"),
    [
        (["user-a", "user-a"], ["user-b"], "duplicate policy IDs: user-a"),
        (["user-a", ""], [], "non-empty policy IDs"),
        (["user-a", None], [], "non-empty policy IDs"),
        ("user-a", [], "must be arrays"),
    ],
)
async def test_reorder_validates_the_request_before_any_read(before, after, message):
    controller = FakeController()
    manager, _ = _manager(controller)

    with pytest.raises(ValueError, match=message):
        await manager.reorder_firewall_policies_v2(SRC, DST, before, after)
    assert controller.calls == []


@pytest.mark.asyncio
async def test_reorders_of_one_pair_run_one_at_a_time():
    controller = FakeController()
    release = asyncio.Event()
    manager, connection = _manager(controller)

    async def held(api_request):
        result = await controller.request(api_request)
        if api_request.method == "put":
            await release.wait()
        return result

    connection.request.side_effect = held
    second_manager = FirewallManager(connection)

    first = asyncio.create_task(manager.reorder_firewall_policies_v2(SRC, DST, ["user-b", "user-a"], ["user-c"]))
    while REORDER not in controller.calls:
        await asyncio.sleep(0)
    second = asyncio.create_task(
        second_manager.reorder_firewall_policies_v2(SRC, DST, ["user-a", "user-b"], ["user-c"])
    )
    for _ in range(20):
        await asyncio.sleep(0)
    assert controller.calls == [ZONE_READ, POLICY_READ, REORDER, ZONE_READ]

    release.set()
    results = await asyncio.gather(first, second)

    assert results == [
        {"before_predefined_ids": ["user-b", "user-a"], "after_predefined_ids": ["user-c"]},
        {"before_predefined_ids": ["user-a", "user-b"], "after_predefined_ids": ["user-c"]},
    ]
    assert controller.calls == [
        ZONE_READ,
        POLICY_READ,
        REORDER,
        ZONE_READ,
        POLICY_READ,
        POLICY_READ,
        REORDER,
        POLICY_READ,
    ]
