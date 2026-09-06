"""NatManager: list/get/create/update/delete/toggle against a recording connection.

The tests assert the outgoing request payloads, because the merge-then-PUT
shape is where a partial update can silently rewrite a stored rule.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from aiounifi.errors import (
    AiounifiException,
    Forbidden,
    LoginRequired,
    NoPermission,
    ResponseError,
    TwoFaTokenRequired,
    Unauthorized,
)
from unifi_core.exceptions import UniFiNotFoundError, UniFiOperationError
from unifi_core.network.managers.nat_manager import CACHE_PREFIX_NAT, NAT_UNAVAILABLE_HINT, NatManager

from tests.network.nat_fixtures import DNS_REDIRECT, dnat

STORED = DNS_REDIRECT
RULE_ID = DNS_REDIRECT["_id"]


class _Connection:
    site = "default"

    def __init__(self, responses: list[Any], error: Exception | None = None, *, fail_on: str | None = None) -> None:
        self.requests: list[Any] = []
        self._responses = responses
        self._error = error
        self._fail_on = fail_on  # raise ``error`` only for requests with this method
        self.cache: dict[str, Any] = {}
        self.invalidated: list[str] = []

    async def ensure_connected(self) -> bool:
        return True

    async def request(self, api_request: Any) -> Any:
        self.requests.append(api_request)
        if self._error is not None and self._fail_on in (None, api_request.method):
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
        manager, connection = _manager([STORED])
        assert await manager.delete_nat_rule(RULE_ID) is True
        request = connection.requests[-1]
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


class TestReviewFindings:
    """Cases the review pass added."""

    @pytest.mark.parametrize("response", [None, "oops", {"data": "oops"}])
    async def test_unparseable_list_response_raises_and_is_not_cached(self, response: Any) -> None:
        manager, connection = _manager(response)
        with pytest.raises(UniFiOperationError):
            await manager.list_nat_rules()
        assert connection.cache == {}

    @pytest.mark.parametrize("response", [None, [], {"data": []}])
    async def test_empty_create_response_raises(self, response: Any) -> None:
        manager, _ = _manager(response)
        with pytest.raises(UniFiOperationError):
            await manager.create_nat_rule(dnat())

    async def test_failed_create_invalidates_the_cache(self) -> None:
        manager, connection = _manager([STORED])
        await manager.list_nat_rules()
        connection._error = RuntimeError("controller said no")
        with pytest.raises(RuntimeError):
            await manager.create_nat_rule(dnat())
        assert CACHE_PREFIX_NAT in connection.invalidated

    async def test_auto_rule_index_reads_a_fresh_list_and_skips_predefined_rules(self) -> None:
        predefined = dict(STORED, _id="rule-p", rule_index=40000, is_predefined=True)
        manager, connection = _manager([STORED], [STORED, predefined], [STORED])
        await manager.list_nat_rules()  # warm the cache
        await manager.create_nat_rule(dnat(rule_index=None))
        assert [r.method for r in connection.requests] == ["get", "get", "post"]
        assert connection.requests[-1].data["rule_index"] == STORED["rule_index"] + 1

    @pytest.mark.parametrize("rule_id", ["rule-9", "../../../../../api/s/default/cmd/sitemgr", "x?y=1"])
    async def test_delete_resolves_the_id_before_sending(self, rule_id: str) -> None:
        manager, connection = _manager([STORED])
        with pytest.raises(UniFiNotFoundError):
            await manager.delete_nat_rule(rule_id)
        assert [r.method for r in connection.requests] == ["get"]

    @pytest.mark.parametrize(
        "error",
        [
            LoginRequired("Call https://host/nat received 401 Unauthorized"),
            Forbidden("Call https://host/nat received 403 Forbidden"),
            NoPermission({"errorCode": 404, "message": "api.err.NoPermission"}),
            Unauthorized({"errorCode": 405, "message": "api.err.Unauthorized"}),
        ],
    )
    async def test_auth_errors_are_never_mapped_to_the_endpoint_hint(self, error: Exception) -> None:
        manager, _ = _manager(error=error)
        with pytest.raises(type(error)) as exc:
            await manager.list_nat_rules()
        assert NAT_UNAVAILABLE_HINT not in str(exc.value)

    async def test_missing_endpoint_is_logged_by_class_only(self, caplog: pytest.LogCaptureFixture) -> None:
        manager, _ = _manager(error=ResponseError("Call https://host/nat received 404 Not Found"))
        with caplog.at_level(logging.DEBUG, logger="unifi-network-mcp"):
            with pytest.raises(UniFiOperationError):
                await manager.list_nat_rules()
        assert "ResponseError" in caplog.text
        assert "host" not in caplog.text
        assert all(record.exc_info is None for record in caplog.records)

    async def test_toggle_defaults_a_missing_enabled_to_true(self) -> None:
        stored = {k: v for k, v in STORED.items() if k != "enabled"}
        manager, connection = _manager([stored])
        await manager.toggle_nat_rule(RULE_ID)
        assert connection.requests[-1].data["enabled"] is True


class TestReReviewFindings:
    async def test_empty_rule_list_is_a_real_answer(self) -> None:
        manager, connection = _manager([])
        assert await manager.list_nat_rules() == []
        assert connection.cache == {f"{CACHE_PREFIX_NAT}_default": []}

    async def test_list_of_non_rules_raises_and_is_not_cached(self) -> None:
        manager, connection = _manager(["oops"])
        with pytest.raises(UniFiOperationError):
            await manager.list_nat_rules()
        assert connection.cache == {}

    async def test_two_factor_error_is_not_mapped_to_the_endpoint_hint(self) -> None:
        error = TwoFaTokenRequired({"errorCode": 404, "message": "api.err.Ubic2faTokenRequired"})
        manager, _ = _manager(error=error)
        with pytest.raises(TwoFaTokenRequired):
            await manager.list_nat_rules()

    async def test_empty_create_response_names_the_ambiguity(self) -> None:
        manager, _ = _manager(None)
        with pytest.raises(UniFiOperationError) as exc:
            await manager.create_nat_rule(dnat())
        assert "may have been created" in str(exc.value)


class TestCachePreservation:
    """Review finding on 4ea1b8d: update/toggle built the replacement document
    from the cached list, so an external change was silently reverted, and a
    PUT/DELETE whose reply never arrived left the stale cache valid."""

    FRESH = dict(STORED, enabled=False, ip_address="192.0.2.54")

    @staticmethod
    def _failing_on(method: str, error: Exception) -> tuple[NatManager, _Connection]:
        connection = _Connection([STORED, STORED, STORED], error, fail_on=method)
        return NatManager(connection), connection

    async def test_update_fetches_fresh_state_before_building_the_replacement(self) -> None:
        manager, connection = _manager([STORED], self.FRESH)
        await manager.list_nat_rules()  # warms the cache with the old document
        await manager.update_nat_rule(RULE_ID, {"description": "Renamed"})
        methods = [r.method for r in connection.requests]
        assert methods == ["get", "get", "put"], "the replacement must come from a fresh list"
        put = connection.requests[-1].data
        assert put["enabled"] is False
        assert put["ip_address"] == "192.0.2.54"
        assert put["description"] == "Renamed"

    async def test_toggle_flips_the_fresh_state_not_the_cached_one(self) -> None:
        manager, connection = _manager([STORED], self.FRESH)
        await manager.list_nat_rules()
        result = await manager.toggle_nat_rule(RULE_ID)
        put = connection.requests[-1].data
        assert put["enabled"] is True  # the fresh document was disabled
        assert put["ip_address"] == "192.0.2.54"
        assert result["enabled"] is True

    async def test_toggle_with_explicit_state_still_uses_the_fresh_document(self) -> None:
        manager, connection = _manager([STORED], self.FRESH)
        await manager.list_nat_rules()
        await manager.toggle_nat_rule(RULE_ID, enabled=False)
        assert connection.requests[-1].data["ip_address"] == "192.0.2.54"

    @pytest.mark.parametrize("error", [TimeoutError("reply timeout"), ResponseError("Call x received 502 bad gateway")])
    async def test_put_with_an_ambiguous_outcome_invalidates_the_cache(self, error: Exception) -> None:
        manager, connection = self._failing_on("put", error)
        await manager.list_nat_rules()
        with pytest.raises(type(error)):
            await manager.update_nat_rule(RULE_ID, {"description": "Renamed"})
        assert CACHE_PREFIX_NAT in connection.invalidated
        assert not [k for k in connection.cache if k.startswith(CACHE_PREFIX_NAT)]

    @pytest.mark.parametrize("error", [TimeoutError("reply timeout"), ResponseError("Call x received 502 bad gateway")])
    async def test_delete_with_an_ambiguous_outcome_invalidates_the_cache(self, error: Exception) -> None:
        manager, connection = self._failing_on("delete", error)
        await manager.list_nat_rules()
        with pytest.raises(type(error)):
            await manager.delete_nat_rule(RULE_ID)
        assert CACHE_PREFIX_NAT in connection.invalidated
        assert not [k for k in connection.cache if k.startswith(CACHE_PREFIX_NAT)]

    async def test_next_read_after_a_failed_put_goes_to_the_controller(self) -> None:
        manager, connection = self._failing_on("put", TimeoutError("reply timeout"))
        await manager.list_nat_rules()
        with pytest.raises(TimeoutError):
            await manager.toggle_nat_rule(RULE_ID)
        gets_before = [r for r in connection.requests if r.method == "get"]
        await manager.get_nat_rule(RULE_ID)
        gets_after = [r for r in connection.requests if r.method == "get"]
        assert len(gets_after) == len(gets_before) + 1
