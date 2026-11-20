"""Firewall policy reads and writes that act on one policy read that one policy.

A site holds hundreds of policies. Reading the whole inventory to find the one
being changed, once in the tool, again in the manager, and again to verify,
made a bulk rename take minutes and stalled the controller UI.
"""

import copy
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiounifi.errors import AiounifiException, Forbidden, ResponseError
from unifi_core.exceptions import UniFiNotFoundError, UniFiOperationError
from unifi_core.network.managers.firewall_manager import FirewallManager

STORED = {
    "_id": "pol001",
    "name": "Admin to NAS",
    "enabled": True,
    "action": "ALLOW",
    "ip_version": "BOTH",
    "protocol": "all",
    "predefined": False,
    "source": {"zone_id": "zone-internal", "matching_target": "ANY"},
    "destination": {
        "zone_id": "zone-internal",
        "matching_target": "IP",
        "matching_target_type": "SPECIFIC",
        "ips": ["192.0.2.10"],
        "port_matching_type": "ANY",
    },
    "schedule": {"mode": "ALWAYS"},
}


def _connection(*responses):
    connection = MagicMock()
    connection.site = "default"
    connection.ensure_connected = AsyncMock(return_value=True)
    connection.request = AsyncMock(side_effect=list(responses))
    connection.get_cached = MagicMock(return_value=None)
    connection._update_cache = MagicMock()
    connection._invalidate_cache = MagicMock()
    return connection


def _manager(connection):
    manager = FirewallManager(connection)
    manager.get_firewall_policies = AsyncMock(side_effect=AssertionError("the full policy list was read"))
    return manager


def _calls(connection):
    return [(call.args[0].method, call.args[0].path) for call in connection.request.await_args_list]


class TestGetFirewallPolicyById:
    @pytest.mark.asyncio
    async def test_reads_the_one_policy(self) -> None:
        connection = _connection([copy.deepcopy(STORED)])

        policy = await _manager(connection).get_firewall_policy_by_id("pol001")

        assert policy.raw == STORED
        assert _calls(connection) == [("get", "/firewall-policies/pol001")]

    @pytest.mark.asyncio
    async def test_accepts_a_bare_document(self) -> None:
        connection = _connection(copy.deepcopy(STORED))

        policy = await _manager(connection).get_firewall_policy_by_id("pol001")

        assert policy.raw == STORED

    @pytest.mark.asyncio
    async def test_an_empty_answer_is_not_found(self) -> None:
        connection = _connection([])

        with pytest.raises(UniFiNotFoundError):
            await _manager(connection).get_firewall_policy_by_id("pol001")

    @pytest.mark.asyncio
    async def test_a_different_policy_in_the_answer_is_not_found(self) -> None:
        """Matched by id, not taken on trust: a controller that ignored the id would
        hand back some other policy to be overwritten."""
        connection = _connection([{**STORED, "_id": "other"}])

        with pytest.raises(UniFiNotFoundError):
            await _manager(connection).get_firewall_policy_by_id("pol001")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "refusal",
        [
            ResponseError("Call /proxy/network/v2/api/site/default/firewall-policies/x received 404 Not Found"),
            AiounifiException({"errorCode": 400, "message": "api.err.InvalidObject"}),
            AiounifiException({"errorCode": 405, "message": "Method Not Allowed"}),
        ],
        ids=["404", "400", "405"],
    )
    async def test_a_refused_single_read_is_settled_by_the_list(self, refusal) -> None:
        connection = _connection(refusal)
        manager = FirewallManager(connection)
        listed = MagicMock(raw=copy.deepcopy(STORED))
        manager.get_firewall_policies = AsyncMock(return_value=[MagicMock(raw={"_id": "other"}), listed])

        assert await manager.get_firewall_policy_by_id("pol001") is listed
        assert _calls(connection) == [("get", "/firewall-policies/pol001")]
        manager.get_firewall_policies.assert_awaited_once_with(include_predefined=True)

        connection.request = AsyncMock(side_effect=[refusal])
        manager.get_firewall_policies = AsyncMock(return_value=[MagicMock(raw={"_id": "other"})])
        with pytest.raises(UniFiNotFoundError):
            await manager.get_firewall_policy_by_id("pol001")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error",
        [
            Forbidden("Call /proxy/network/v2/api/site/default/firewall-policies/x received 403 Forbidden"),
            AiounifiException({"errorCode": 500, "message": "api.err.ServerError"}),
            ConnectionError("reset"),
        ],
        ids=["forbidden", "500", "transport"],
    )
    async def test_other_failures_propagate(self, error) -> None:
        connection = _connection(error)

        with pytest.raises(type(error)):
            await _manager(connection).get_firewall_policy_by_id("pol001")

    @pytest.mark.asyncio
    async def test_an_unreadable_answer_is_not_a_miss(self) -> None:
        connection = _connection("<html>restarting</html>")

        with pytest.raises(UniFiOperationError):
            await _manager(connection).get_firewall_policy_by_id("pol001")

    @pytest.mark.asyncio
    async def test_an_id_that_is_not_one_path_segment_never_reaches_the_controller(self) -> None:
        connection = _connection()

        with pytest.raises(ValueError):
            await _manager(connection).get_firewall_policy_by_id("../pol001")
        connection.request.assert_not_awaited()


class TestUpdateFirewallPolicyReads:
    @pytest.mark.asyncio
    async def test_without_current_reads_the_one_policy_then_puts(self) -> None:
        connection = _connection([copy.deepcopy(STORED)], [{**STORED, "name": "Renamed"}])

        assert await _manager(connection).update_firewall_policy("pol001", {"name": "Renamed"}) is True

        assert _calls(connection) == [("get", "/firewall-policies/pol001"), ("put", "/firewall-policies/pol001")]
        body = connection.request.await_args_list[1].args[0].data
        assert body == {**STORED, "name": "Renamed"}

    @pytest.mark.asyncio
    async def test_with_current_puts_without_reading(self) -> None:
        connection = _connection([{**STORED, "name": "Renamed"}])
        current = copy.deepcopy(STORED)

        assert await _manager(connection).update_firewall_policy("pol001", {"name": "Renamed"}, current=current) is True

        assert _calls(connection) == [("put", "/firewall-policies/pol001")]
        assert connection.request.await_args.args[0].data == {**STORED, "name": "Renamed"}
        assert current == STORED

    @pytest.mark.asyncio
    async def test_without_current_a_missing_policy_raises_before_any_put(self) -> None:
        connection = _connection([])

        with pytest.raises(UniFiNotFoundError):
            await _manager(connection).update_firewall_policy("pol001", {"name": "Renamed"})
        assert _calls(connection) == [("get", "/firewall-policies/pol001")]

    @pytest.mark.asyncio
    async def test_retired_address_selectors_are_removed_from_the_put_body(self) -> None:
        """Moving a destination from specific IPs to an IP group must not store the old
        ips beside the group, where they come back into force on a switch back."""
        connection = _connection([{}])
        update = {"destination": {"matching_target": "IP", "matching_target_type": "OBJECT", "ip_group_id": "grp1"}}

        await _manager(connection).update_firewall_policy("pol001", update, current=copy.deepcopy(STORED))

        destination = connection.request.await_args.args[0].data["destination"]
        assert destination == {
            "zone_id": "zone-internal",
            "matching_target": "IP",
            "matching_target_type": "OBJECT",
            "ip_group_id": "grp1",
            "port_matching_type": "ANY",
        }

    @pytest.mark.asyncio
    async def test_leaving_network_removes_network_ids_from_the_put_body(self) -> None:
        stored = copy.deepcopy(STORED)
        stored["source"] = {
            "zone_id": "zone-internal",
            "matching_target": "NETWORK",
            "matching_target_type": "OBJECT",
            "network_ids": ["net-iot"],
            "match_opposite_networks": True,
        }
        connection = _connection([{}])

        await _manager(connection).update_firewall_policy(
            "pol001", {"source": {"matching_target": "ANY"}}, current=stored
        )

        source = connection.request.await_args.args[0].data["source"]
        assert source == {
            "zone_id": "zone-internal",
            "matching_target": "ANY",
            "matching_target_type": "OBJECT",
            "match_opposite_networks": False,
        }


class TestToggleFirewallPolicyReads:
    @pytest.mark.asyncio
    async def test_reads_the_one_policy_once_then_puts(self) -> None:
        connection = _connection([copy.deepcopy(STORED)], [{**STORED, "enabled": False}])

        assert await _manager(connection).toggle_firewall_policy("pol001") is True

        assert _calls(connection) == [("get", "/firewall-policies/pol001"), ("put", "/firewall-policies/pol001")]
        assert connection.request.await_args.args[0].data == {**STORED, "enabled": False}

    @pytest.mark.asyncio
    async def test_a_missing_policy_raises_without_a_put(self) -> None:
        connection = _connection([])

        with pytest.raises(UniFiNotFoundError):
            await _manager(connection).toggle_firewall_policy("pol001")
        assert _calls(connection) == [("get", "/firewall-policies/pol001")]
