"""NatManager: list/get/create/update/delete/toggle against a recording connection.

The tests assert the outgoing request payloads, because the merge-then-PUT
shape is where a partial update can silently rewrite a stored rule.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from aiounifi.errors import AiounifiException, ResponseError
from unifi_core.exceptions import UniFiNotFoundError, UniFiOperationError
from unifi_core.network.managers.nat_manager import CACHE_PREFIX_NAT, NAT_UNAVAILABLE_HINT, NatManager

from tests.network.nat_fixtures import DNS_REDIRECT, dnat

STORED = DNS_REDIRECT
RULE_ID = DNS_REDIRECT["_id"]


class _Connection:
    site = "default"

    def __init__(self, responses: list[Any], error: Exception | None = None) -> None:
        self.requests: list[Any] = []
        self._responses = responses
        self._error = error
        self.cache: dict[str, Any] = {}
        self.invalidated: list[str] = []

    async def ensure_connected(self) -> bool:
        return True

    async def request(self, api_request: Any) -> Any:
        self.requests.append(api_request)
        if self._error is not None:
            raise self._error
        return self._responses.pop(0) if self._responses else None

    def get_cached(self, key: str) -> Any:
        return self.cache.get(key)

    def _update_cache(self, key: str, value: Any) -> None:
        self.cache[key] = value

    def _invalidate_cache(self, prefix: str) -> None:
        self.invalidated.append(prefix)
        self.cache = {k: v for k, v in self.cache.items() if not k.startswith(prefix)}


def _manager(*responses: Any, error: Exception | None = None) -> tuple[NatManager, _Connection]:
    """Queue one controller response per request, in order; unqueued requests answer ``None``."""
    connection = _Connection(list(responses), error)
    return NatManager(connection), connection


class TestList:
    async def test_bare_list_response(self) -> None:
        manager, connection = _manager([STORED])
        assert await manager.list_nat_rules() == [STORED]
        request = connection.requests[0]
        assert (request.method, request.path) == ("get", "/nat")

    async def test_data_wrapped_response(self) -> None:
        manager, _ = _manager({"data": [STORED]})
        assert await manager.list_nat_rules() == [STORED]

    async def test_uses_and_fills_the_cache(self) -> None:
        manager, connection = _manager([STORED])
        await manager.list_nat_rules()
        await manager.list_nat_rules()
        assert len(connection.requests) == 1
        assert list(connection.cache) == [f"{CACHE_PREFIX_NAT}_default"]

    @pytest.mark.parametrize(
        "error",
        [
            ResponseError("Call https://host/proxy/network/v2/api/site/default/nat received 404 Not Found"),
            AiounifiException({"errorCode": 405, "message": "Method Not Allowed"}),
        ],
    )
    async def test_missing_endpoint_becomes_an_actionable_error(self, error: Exception) -> None:
        manager, _ = _manager(error=error)
        with pytest.raises(UniFiOperationError) as exc:
            await manager.list_nat_rules()
        assert NAT_UNAVAILABLE_HINT in str(exc.value)

    async def test_other_controller_errors_surface_unchanged(self) -> None:
        manager, _ = _manager(error=ResponseError("Call https://host/nat received 429: b''"))
        with pytest.raises(ResponseError):
            await manager.list_nat_rules()


class TestGet:
    async def test_returns_matching_rule(self) -> None:
        manager, _ = _manager([STORED])
        assert await manager.get_nat_rule(RULE_ID) == STORED

    async def test_missing_rule_raises_not_found(self) -> None:
        manager, _ = _manager([STORED])
        with pytest.raises(UniFiNotFoundError) as exc:
            await manager.get_nat_rule("rule-9")
        assert exc.value.resource_type == "nat_rule"


class TestCreate:
    async def test_posts_normalized_rule_and_returns_created(self) -> None:
        created = dict(STORED, _id="rule-2")
        manager, connection = _manager([created])
        result = await manager.create_nat_rule(dnat(type="dnat", rule_index=7))
        assert result == created
        post = connection.requests[-1]
        assert (post.method, post.path) == ("post", "/nat")
        assert post.data["type"] == "DNAT"
        assert post.data["rule_index"] == 7
        assert CACHE_PREFIX_NAT in connection.invalidated

    async def test_assigns_the_next_rule_index_when_absent(self) -> None:
        manager, connection = _manager([STORED, dict(STORED, _id="rule-3", rule_index=11)], [STORED])
        await manager.create_nat_rule(dnat(rule_index=None))
        assert connection.requests[-1].data["rule_index"] == 12

    async def test_first_rule_gets_index_one(self) -> None:
        manager, connection = _manager([], [STORED])
        await manager.create_nat_rule(dnat(rule_index=None))
        assert connection.requests[-1].data["rule_index"] == 1

    async def test_rejects_unknown_fields_before_any_request(self) -> None:
        manager, connection = _manager()
        with pytest.raises(ValueError) as exc:
            await manager.create_nat_rule(dnat(bogus=1))
        assert "bogus" in str(exc.value)
        assert connection.requests == []

    async def test_rejects_invalid_rule_before_any_request(self) -> None:
        manager, connection = _manager()
        with pytest.raises(ValueError) as exc:
            await manager.create_nat_rule(dnat(port="0", rule_index=None))
        assert "'0'" in str(exc.value)
        assert connection.requests == []

    async def test_bare_dict_response_is_returned(self) -> None:
        created = dict(STORED, _id="rule-2")
        manager, _ = _manager(created)
        assert await manager.create_nat_rule(dnat()) == created


class TestUpdate:
    async def test_merges_over_the_stored_rule_and_puts_everything(self) -> None:
        manager, connection = _manager([STORED])
        result = await manager.update_nat_rule(RULE_ID, {"description": "Renamed"})
        put = connection.requests[-1]
        assert (put.method, put.path) == ("put", f"/nat/{RULE_ID}")
        assert put.data == dict(STORED, description="Renamed")
        assert result == put.data
        assert CACHE_PREFIX_NAT in connection.invalidated

    async def test_partial_filter_update_keeps_sibling_keys(self) -> None:
        manager, connection = _manager([STORED])
        await manager.update_nat_rule(RULE_ID, {"destination_filter": {"port": "853"}})
        sent = connection.requests[-1].data["destination_filter"]
        assert sent == dict(STORED["destination_filter"], port="853")

    async def test_switching_filter_type_drops_the_stale_selectors(self) -> None:
        manager, connection = _manager([STORED])
        await manager.update_nat_rule(
            RULE_ID, {"destination_filter": {"filter_type": "firewall_groups", "firewall_group_ids": ["g1"]}}
        )
        sent = connection.requests[-1].data["destination_filter"]
        assert sent == {
            "filter_type": "FIREWALL_GROUPS",
            "firewall_group_ids": ["g1"],
            "invert_address": True,
            "invert_port": False,
        }

    async def test_switching_to_masquerade_drops_the_translation(self) -> None:
        manager, connection = _manager([STORED])
        await manager.update_nat_rule(RULE_ID, {"type": "masquerade", "out_interface": "wan-1"})
        sent = connection.requests[-1].data
        assert sent["type"] == "MASQUERADE"
        assert "ip_address" not in sent
        assert "port" not in sent

    async def test_reports_only_errors_the_update_introduces(self) -> None:
        stored = dict(STORED, port="bogus")
        manager, connection = _manager([stored])
        await manager.update_nat_rule(RULE_ID, {"enabled": False})
        assert connection.requests[-1].method == "put"
        manager, connection = _manager([stored])
        with pytest.raises(ValueError) as exc:
            await manager.update_nat_rule(RULE_ID, {"port": "worse"})
        assert "'worse'" in str(exc.value)
        assert all(r.method == "get" for r in connection.requests)

    async def test_rejects_unknown_fields_before_any_request(self) -> None:
        manager, connection = _manager([STORED])
        with pytest.raises(ValueError):
            await manager.update_nat_rule(RULE_ID, {"is_predefined": True})
        assert connection.requests == []

    async def test_empty_update_returns_stored_without_a_put(self) -> None:
        manager, connection = _manager([STORED])
        assert await manager.update_nat_rule(RULE_ID, {"port": None}) == STORED
        assert all(r.method == "get" for r in connection.requests)

    async def test_missing_rule_raises_not_found(self) -> None:
        manager, _ = _manager([STORED])
        with pytest.raises(UniFiNotFoundError):
            await manager.update_nat_rule("rule-9", {"enabled": False})


class TestDeleteAndToggle:
    async def test_delete_sends_delete_and_invalidates(self) -> None:
        manager, connection = _manager()
        assert await manager.delete_nat_rule(RULE_ID) is True
        request = connection.requests[0]
        assert (request.method, request.path) == ("delete", f"/nat/{RULE_ID}")
        assert CACHE_PREFIX_NAT in connection.invalidated

    async def test_toggle_flips_enabled_with_one_fetch(self) -> None:
        manager, connection = _manager([STORED])
        result = await manager.toggle_nat_rule(RULE_ID)
        assert [r.method for r in connection.requests] == ["get", "put"]
        assert connection.requests[-1].data == dict(STORED, enabled=False)
        assert result["enabled"] is False

    async def test_toggle_with_explicit_state(self) -> None:
        manager, connection = _manager([STORED])
        await manager.toggle_nat_rule(RULE_ID, enabled=True)
        assert connection.requests[-1].data["enabled"] is True

    async def test_toggle_missing_rule_raises_not_found(self) -> None:
        manager, _ = _manager([STORED])
        with pytest.raises(UniFiNotFoundError):
            await manager.toggle_nat_rule("rule-9")


class TestLogging:
    @pytest.mark.parametrize(
        "call",
        [
            lambda m: m.delete_nat_rule(RULE_ID),
            lambda m: m.list_nat_rules(),
            lambda m: m.create_nat_rule(dnat()),
        ],
    )
    async def test_failure_logs_carry_no_values_or_exception_text(self, caplog: pytest.LogCaptureFixture, call) -> None:
        private = f"192.0.2.53 secret-name password=private {RULE_ID}"
        manager, _ = _manager(error=RuntimeError(private))
        with caplog.at_level(logging.DEBUG, logger="unifi-network-mcp"):
            with pytest.raises(RuntimeError):
                await call(manager)
        assert caplog.records
        for value in ("192.0.2.53", "secret-name", "private", RULE_ID):
            assert value not in caplog.text
            assert all(value not in repr(record.args) for record in caplog.records)
        assert all(record.exc_info is None for record in caplog.records)
        assert "RuntimeError" in caplog.text

    async def test_update_failure_logs_no_values(self, caplog: pytest.LogCaptureFixture) -> None:
        manager, connection = _manager([STORED])
        connection._error = None
        await manager.list_nat_rules()  # prime the cache so the PUT is the failing request
        connection._error = RuntimeError("192.0.2.53 password=private")
        with caplog.at_level(logging.DEBUG, logger="unifi-network-mcp"):
            with pytest.raises(RuntimeError):
                await manager.update_nat_rule(RULE_ID, {"enabled": False})
        assert "192.0.2.53" not in caplog.text and "private" not in caplog.text
        assert all(record.exc_info is None for record in caplog.records)
        assert "RuntimeError" in caplog.text
