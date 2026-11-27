"""Whole-chain ACL rule ordering: previewing, rewriting and reading back the order."""

import copy
from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.exceptions import UniFiMalformedResponseError, UniFiOperationError
from unifi_core.network.managers.acl_manager import AclManager

NETWORK = "net-1"
OTHER_NETWORK = "net-2"


def _rule(rule_id, index, network=NETWORK, name=None):
    return {
        "_id": rule_id,
        "acl_index": index,
        "name": name or rule_id,
        "mac_acl_network_id": network,
        "action": "ALLOW",
        "type": "MAC",
        "traffic_source": {"type": "MAC", "specific_mac_addresses": []},
    }


def _chain():
    return [
        _rule("rule-a", 0),
        _rule("rule-b", 1),
        _rule("rule-c", 2),
        _rule("other-rule", 0, network=OTHER_NETWORK),
    ]


class FakeController:
    """Answers ACL list reads and applies reorder PUTs to the stored rules."""

    def __init__(self, rules=None, apply_writes=True):
        self.rules = _chain() if rules is None else copy.deepcopy(rules)
        self.apply_writes = apply_writes
        self.calls = []
        self.puts = []

    async def request(self, api_request):
        self.calls.append((api_request.method, api_request.path))
        if api_request.method == "get":
            return copy.deepcopy(self.rules)
        self.puts.append((api_request.path, copy.deepcopy(api_request.data)))
        if self.apply_writes:
            rule_id = api_request.path.rsplit("/", 1)[1]
            for rule in self.rules:
                if rule["_id"] == rule_id:
                    rule.update(copy.deepcopy(api_request.data))
        return {}


def _manager(controller):
    connection = MagicMock()
    connection.site = "default"
    connection.ensure_connected = AsyncMock(return_value=True)
    connection.request = AsyncMock(side_effect=controller.request)
    connection.get_cached = MagicMock(return_value=None)
    connection._update_cache = MagicMock()
    connection._invalidate_cache = MagicMock()
    return AclManager(connection), connection


@pytest.mark.asyncio
async def test_preview_reports_current_and_requested_order_without_writing():
    controller = FakeController()
    manager, _ = _manager(controller)

    preview = await manager.preview_acl_rule_order(NETWORK, ["rule-c", "rule-a", "rule-b"])

    assert [entry["rule_id"] for entry in preview["current"]] == ["rule-a", "rule-b", "rule-c"]
    assert [entry["acl_index"] for entry in preview["current"]] == [0, 1, 2]
    assert [entry["rule_id"] for entry in preview["requested"]] == ["rule-c", "rule-a", "rule-b"]
    assert preview["requested"][0]["name"] == "rule-c"
    assert controller.puts == []


@pytest.mark.asyncio
async def test_preview_scopes_to_the_requested_network():
    manager, _ = _manager(FakeController())

    preview = await manager.preview_acl_rule_order(NETWORK, ["rule-a", "rule-b", "rule-c"])

    assert "other-rule" not in [entry["rule_id"] for entry in preview["current"]]


@pytest.mark.asyncio
async def test_preview_refuses_a_list_that_does_not_match_the_chain():
    manager, _ = _manager(FakeController())

    with pytest.raises(ValueError) as excinfo:
        await manager.preview_acl_rule_order(NETWORK, ["rule-a", "rule-b"])

    message = str(excinfo.value)
    assert "Missing: rule-c" in message
    assert "unexpected: none" in message


@pytest.mark.asyncio
async def test_preview_refuses_an_unknown_rule_id():
    manager, _ = _manager(FakeController())

    with pytest.raises(ValueError) as excinfo:
        await manager.preview_acl_rule_order(NETWORK, ["rule-a", "rule-b", "rule-c", "ghost"])

    assert "unexpected: ghost" in str(excinfo.value)


@pytest.mark.asyncio
async def test_set_rewrites_the_chain_in_the_requested_order():
    controller = FakeController()
    manager, _ = _manager(controller)

    result = await manager.set_acl_rule_order(NETWORK, ["rule-c", "rule-a", "rule-b"])

    assert result["ordered_rule_ids"] == ["rule-c", "rule-a", "rule-b"]
    assert result["acl_indices"] == {"rule-c": 0, "rule-a": 1, "rule-b": 2}
    assert [path for path, _payload in controller.puts] == [
        "/acl-rules/rule-c",
        "/acl-rules/rule-a",
        "/acl-rules/rule-b",
    ]
    assert [payload["acl_index"] for _path, payload in controller.puts] == [0, 1, 2]
    # Each PUT carries the rule's full current payload, not just the index.
    assert controller.puts[0][1]["name"] == "rule-c"
    assert controller.puts[0][1]["mac_acl_network_id"] == NETWORK


@pytest.mark.asyncio
async def test_set_leaves_other_networks_untouched():
    controller = FakeController()
    manager, _ = _manager(controller)

    await manager.set_acl_rule_order(NETWORK, ["rule-b", "rule-a", "rule-c"])

    assert all(path != "/acl-rules/other-rule" for path, _payload in controller.puts)


@pytest.mark.asyncio
async def test_set_raises_when_the_controller_reports_a_different_order():
    controller = FakeController(apply_writes=False)
    manager, _ = _manager(controller)

    with pytest.raises(UniFiOperationError) as excinfo:
        await manager.set_acl_rule_order(NETWORK, ["rule-c", "rule-a", "rule-b"])

    assert "different chain" in str(excinfo.value)


@pytest.mark.asyncio
async def test_set_refuses_duplicate_rule_ids():
    controller = FakeController()
    manager, _ = _manager(controller)

    with pytest.raises(ValueError):
        await manager.set_acl_rule_order(NETWORK, ["rule-a", "rule-a", "rule-b"])

    assert controller.puts == []


@pytest.mark.asyncio
async def test_set_on_an_empty_chain_writes_nothing():
    controller = FakeController(rules=[_rule("other-rule", 0, network=OTHER_NETWORK)])
    manager, _ = _manager(controller)

    result = await manager.set_acl_rule_order(NETWORK, [])

    assert result["ordered_rule_ids"] == []
    assert controller.puts == []


@pytest.mark.asyncio
async def test_malformed_rule_without_an_index_is_refused():
    rules = [_rule("rule-a", 0), _rule("rule-b", 1), {**_rule("rule-c", 2), "acl_index": None}]
    manager, _ = _manager(FakeController(rules=rules))

    with pytest.raises(UniFiMalformedResponseError):
        await manager.preview_acl_rule_order(NETWORK, ["rule-a", "rule-b", "rule-c"])


@pytest.mark.asyncio
async def test_set_invalidates_the_acl_cache():
    controller = FakeController()
    manager, connection = _manager(controller)

    await manager.set_acl_rule_order(NETWORK, ["rule-a", "rule-b", "rule-c"])

    assert connection._invalidate_cache.called
