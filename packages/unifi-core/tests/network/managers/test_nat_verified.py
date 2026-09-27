"""Verified NAT writes use one attempt and fresh V2 readback."""

from copy import deepcopy

import pytest
from aiounifi.errors import ResponseError
from unifi_core.exceptions import UniFiOperationError
from unifi_core.network.managers.nat_manager import CACHE_PREFIX_NAT, NatManager
from unifi_core.network.models.nat import nat_write_input_schema, normalize_nat_create, normalize_nat_verified_write

from tests.network.managers.test_nat_manager import _Connection
from tests.network.nat_fixtures import DNS_REDIRECT


def _new_rule():
    return {
        "type": "DNAT",
        "protocol": "tcp_udp",
        "ip_version": "IPV4",
        "in_interface": "network-1",
        "ip_address": "192.0.2.53",
        "destination_filter": {"filter_type": "ADDRESS_AND_PORT", "port": "53"},
    }


def _snat_rule():
    return {
        "type": "SNAT",
        "protocol": "tcp_udp",
        "ip_version": "IPV4",
        "out_interface": "network-2",
        "ip_address": "192.0.2.53",
        "port": "53",
        "source_filter": {"filter_type": "ADDRESS_AND_PORT", "port": "53"},
    }


def _manager(*responses, error=None, fail_on=None):
    connection = _Connection(list(responses), error, fail_on=fail_on)
    return NatManager(connection), connection


def test_strict_write_rejects_nested_typos_and_values_without_echo():
    secret = "192.0.2.77 private"
    for fields in (
        {"destination_filter": {"adress": secret}},
        {"destination_filter": {"address": secret}},
        {"destination_filter": {"port": "99999"}},
        {"destination_filter": {"invert_address": True}},
        {"destination_filter": {"filter_type": "IID_AND_PORT"}},
        {"ip_version": "IPV6"},
        {"exclude": True},
        {"_id": secret},
    ):
        with pytest.raises(ValueError) as error:
            normalize_nat_verified_write(fields)
        assert secret not in str(error.value)
    schema = nat_write_input_schema()
    assert "$defs" not in schema
    assert schema["additionalProperties"] is False
    nested = schema["properties"]["destination_filter"]["anyOf"][0]
    assert nested["additionalProperties"] is False


@pytest.mark.asyncio
async def test_default_disabled_and_nested_subset_verify_with_controller_defaults():
    submitted = _new_rule()
    after = {
        **submitted,
        "_id": "nat-2",
        "enabled": False,
        "rule_index": 1,
        "setting_preference": "manual",
        "is_predefined": False,
        "destination_filter": {
            **submitted["destination_filter"],
            "firewall_group_ids": [],
            "invert_address": False,
            "invert_port": False,
        },
    }
    manager, connection = _manager([], {"data": [after]}, [after])
    result = await manager.create_nat_rule_verified(submitted)
    assert result.success is True
    assert result.mutation_applied is True
    assert "destination_filter.port" in result.persisted_fields
    assert [r.method for r in connection.requests] == ["get", "post", "get"]
    assert connection.requests[1].data["enabled"] is False
    assert connection.requests[1].data["rule_index"] == 1
    assert connection.requests[1].data["setting_preference"] == "manual"
    assert connection.requests[1].data["is_predefined"] is False
    assert {"setting_preference", "is_predefined"} <= set(result.persisted_fields)
    assert result.resource["id"] == "nat-2"


@pytest.mark.asyncio
async def test_legacy_create_still_omits_default_enabled():
    from tests.network.nat_fixtures import dnat

    manager, connection = _manager([{"_id": "nat-2"}])
    fields = dnat(rule_index=1)
    fields.pop("enabled")
    await manager.create_nat_rule(fields)
    assert "enabled" not in connection.requests[0].data
    assert "setting_preference" not in connection.requests[0].data
    assert "is_predefined" not in connection.requests[0].data


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source_filter",
    [{"filter_type": "NONE"}, {"filter_type": "ADDRESS_AND_PORT", "address": "198.51.100.1"}],
)
async def test_snat_translation_port_without_source_port_fails_before_create(source_filter):
    fields = {**_snat_rule(), "source_filter": source_filter, "rule_index": 1}
    manager, connection = _manager()
    result = await manager.create_nat_rule_verified(fields)
    assert result.success is False and result.mutation_applied is False
    assert "source_filter.port" in result.error
    assert connection.requests == []


@pytest.mark.asyncio
async def test_snat_translation_port_with_source_port_creates_once():
    fields = _snat_rule()
    after = {
        **fields,
        "_id": "nat-snat",
        "enabled": False,
        "rule_index": 1,
        "setting_preference": "manual",
        "is_predefined": False,
    }
    manager, connection = _manager([], {"data": [after]}, [after])
    result = await manager.create_nat_rule_verified(fields)
    assert result.success is True and result.mutation_applied is True
    assert [request.method for request in connection.requests] == ["get", "post", "get"]
    assert connection.requests[1].data["source_filter"]["port"] == "53"
    assert "source_filter.port" in result.persisted_fields


def test_legacy_snat_create_retains_existing_validation_contract():
    fields = {**_snat_rule(), "source_filter": {"filter_type": "NONE"}}
    assert normalize_nat_create(fields) == fields


@pytest.mark.asyncio
async def test_verified_create_reports_dropped_manual_origin():
    # Observed live: an omitted preference remains absent, even for a newly
    # created, disabled, non-predefined rule. Do not report that as editable.
    after = {**_new_rule(), "_id": "nat-new", "enabled": False, "is_predefined": False, "rule_index": 1}
    manager, connection = _manager([], {"data": [after]}, [after])
    result = await manager.create_nat_rule_verified(_new_rule())
    assert result.success is False and result.mutation_applied is True
    assert result.dropped_fields == ("setting_preference",)
    assert [request.method for request in connection.requests] == ["get", "post", "get"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["update", "toggle", "delete"])
async def test_missing_origin_never_authorizes_existing_rule_mutations(operation):
    stored = deepcopy(DNS_REDIRECT)
    stored.pop("setting_preference")
    stored["is_predefined"] = False
    manager, connection = _manager([stored])
    if operation == "update":
        result = await manager.update_nat_rule_verified(stored["_id"], {"description": "changed"})
    elif operation == "toggle":
        result = await manager.toggle_nat_rule_verified(stored["_id"], False)
    else:
        result = await manager.delete_nat_rule_verified(stored["_id"])
    assert result.success is False and result.mutation_applied is False
    assert [request.method for request in connection.requests] == ["get"]


@pytest.mark.asyncio
async def test_preflight_and_noop_send_no_write():
    stored = deepcopy(DNS_REDIRECT)
    manager, connection = _manager([stored], [stored])
    before, after = await manager.preview_nat_update(stored["_id"], {"enabled": True})
    result = await manager.toggle_nat_rule_verified(stored["_id"], True)
    assert before == after
    assert result.success is True and result.mutation_applied is False
    assert [r.method for r in connection.requests] == ["get", "get"]


@pytest.mark.asyncio
async def test_update_preserves_unknown_fields_and_retires_selector():
    stored = deepcopy(DNS_REDIRECT)
    stored["source_filter"]["controller_only"] = {"future": True}
    updated = deepcopy(stored)
    updated["type"] = "SNAT"
    updated["out_interface"] = "network-2"
    updated["description"] = "Changed"
    updated["source_filter"].update(filter_type="ADDRESS_AND_PORT", port="53")
    updated["destination_filter"] = {
        "filter_type": "NONE",
        "firewall_group_ids": [],
        "invert_address": True,
        "invert_port": False,
    }
    manager, connection = _manager([stored], {}, [updated])
    result = await manager.update_nat_rule_verified(
        stored["_id"],
        {
            "type": "SNAT",
            "out_interface": "network-2",
            "description": "Changed",
            "source_filter": {"filter_type": "ADDRESS_AND_PORT", "port": "53"},
            "destination_filter": {"filter_type": "NONE"},
        },
    )
    assert result.success is True
    put = connection.requests[1].data
    assert put["source_filter"]["controller_only"] == {"future": True}
    assert put["ip_address"] == stored["ip_address"]
    assert "address" not in put["destination_filter"]
    assert "port" not in put["destination_filter"]
    assert "destination_filter.port" in result.persisted_fields


@pytest.mark.asyncio
async def test_snat_translation_port_without_source_port_fails_before_update():
    stored = {
        **DNS_REDIRECT,
        "type": "SNAT",
        "out_interface": "network-2",
        "source_filter": {"filter_type": "ADDRESS_AND_PORT", "address": "198.51.100.1"},
    }
    stored.pop("port")
    manager, connection = _manager([stored])
    result = await manager.update_nat_rule_verified(stored["_id"], {"port": "53"})
    assert result.success is False and result.mutation_applied is False
    assert "source_filter.port" in result.error
    assert [request.method for request in connection.requests] == ["get"]


@pytest.mark.asyncio
async def test_snat_filter_retirement_cannot_remove_required_source_port():
    stored = {
        **DNS_REDIRECT,
        "type": "SNAT",
        "out_interface": "network-2",
        "source_filter": {"filter_type": "ADDRESS_AND_PORT", "port": "53"},
    }
    manager, connection = _manager([stored])
    result = await manager.update_nat_rule_verified(stored["_id"], {"source_filter": {"filter_type": "NONE"}})
    assert result.success is False and result.mutation_applied is False
    assert "source_filter.port" in result.error
    assert [request.method for request in connection.requests] == ["get"]


@pytest.mark.asyncio
async def test_snat_source_port_and_translation_port_update_together():
    stored = {
        **DNS_REDIRECT,
        "type": "SNAT",
        "out_interface": "network-2",
        "source_filter": {"filter_type": "ADDRESS_AND_PORT", "address": "198.51.100.1"},
    }
    stored.pop("port")
    after = {**stored, "port": "53", "source_filter": {**stored["source_filter"], "port": "53"}}
    manager, connection = _manager([stored], {}, [after])
    result = await manager.update_nat_rule_verified(stored["_id"], {"port": "53", "source_filter": {"port": "53"}})
    assert result.success is True and result.mutation_applied is True
    assert [request.method for request in connection.requests] == ["get", "put", "get"]
    assert connection.requests[1].data["source_filter"] == after["source_filter"]
    assert "source_filter.port" in result.persisted_fields


@pytest.mark.asyncio
async def test_mismatch_uncertain_and_definite_rejection_are_distinct():
    stored = deepcopy(DNS_REDIRECT)
    manager, connection = _manager([stored], {}, [stored])
    result = await manager.update_nat_rule_verified(stored["_id"], {"description": "Changed"})
    assert result.success is False and result.mutation_applied is True
    assert "description" in result.dropped_fields
    assert len([r for r in connection.requests if r.method == "put"]) == 1

    manager, connection = _manager([stored], error=TimeoutError("secret"), fail_on="put")
    result = await manager.update_nat_rule_verified(stored["_id"], {"description": "Changed"})
    assert result.mutation_applied is None
    assert len([r for r in connection.requests if r.method == "put"]) == 1
    assert CACHE_PREFIX_NAT in connection.invalidated
    assert "secret" not in result.error

    manager, connection = _manager([stored], error=ResponseError("Call secret received 409 conflict"), fail_on="put")
    result = await manager.update_nat_rule_verified(stored["_id"], {"description": "Changed"})
    assert result.mutation_applied is False
    assert len([r for r in connection.requests if r.method == "put"]) == 1

    manager, connection = _manager([stored], {}, None)
    result = await manager.update_nat_rule_verified(stored["_id"], {"description": "Changed"})
    assert result.mutation_applied is None
    assert len([r for r in connection.requests if r.method == "put"]) == 1


@pytest.mark.asyncio
async def test_create_ambiguous_responses_and_delete_absence():
    fields = {**_new_rule(), "rule_index": 1}
    for response in ([], [{"_id": "one"}, {"_id": "two"}]):
        manager, connection = _manager(response)
        result = await manager.create_nat_rule_verified(fields)
        assert result.mutation_applied is None
        assert [r.method for r in connection.requests] == ["post"]

    stored = deepcopy(DNS_REDIRECT)
    manager, connection = _manager([stored], {}, [])
    result = await manager.delete_nat_rule_verified(stored["_id"])
    assert result.success and result.mutation_applied is True
    assert [r.method for r in connection.requests] == ["get", "delete", "get"]


@pytest.mark.asyncio
async def test_create_missing_readback_and_duplicate_index_never_retry():
    fields = {**_new_rule(), "rule_index": 1}
    manager, connection = _manager({"_id": "nat-2"}, [])
    result = await manager.create_nat_rule_verified(fields)
    assert result.mutation_applied is None
    assert [r.method for r in connection.requests] == ["post", "get"]

    manager, connection = _manager(
        [], error=ResponseError("Call secret received 409 duplicate rule_index"), fail_on="post"
    )
    fields.pop("rule_index")
    result = await manager.create_nat_rule_verified(fields)
    assert result.mutation_applied is False
    assert [r.method for r in connection.requests] == ["get", "post"]


@pytest.mark.asyncio
async def test_retired_selector_remaining_is_persistence_mismatch():
    stored = deepcopy(DNS_REDIRECT)
    after = {**stored, "type": "SNAT", "out_interface": "network-2"}
    after["source_filter"] = {**stored["source_filter"], "filter_type": "ADDRESS_AND_PORT", "port": "53"}
    after["destination_filter"] = {**stored["destination_filter"], "filter_type": "NONE"}
    manager, connection = _manager([stored], {}, [after])
    result = await manager.update_nat_rule_verified(
        stored["_id"],
        {
            "type": "SNAT",
            "out_interface": "network-2",
            "source_filter": {"filter_type": "ADDRESS_AND_PORT", "port": "53"},
            "destination_filter": {"filter_type": "NONE"},
        },
    )
    assert result.success is False
    assert "destination_filter.port" in result.dropped_fields
    assert len([r for r in connection.requests if r.method == "put"]) == 1


@pytest.mark.asyncio
async def test_unavailable_session_is_preflight_rejection():
    fields = {**_new_rule(), "rule_index": 1}
    manager, connection = _manager()

    async def unavailable():
        return False

    connection.ensure_connected = unavailable
    result = await manager.create_nat_rule_verified(fields)
    assert result.mutation_applied is False
    assert connection.requests == []


@pytest.mark.asyncio
async def test_unknown_or_managed_id_refused_without_mutation():
    stored = deepcopy(DNS_REDIRECT)
    stored["is_predefined"] = True
    manager, connection = _manager([stored], [stored], [])
    assert (await manager.delete_nat_rule_verified(stored["_id"])).mutation_applied is False
    assert (await manager.update_nat_rule_verified(stored["_id"], {"enabled": False})).mutation_applied is False
    assert (await manager.delete_nat_rule_verified("missing")).mutation_applied is False
    assert all(r.method == "get" for r in connection.requests)

    auto = {**DNS_REDIRECT, "setting_preference": "auto"}
    manager, connection = _manager([auto])
    assert (await manager.update_nat_rule_verified(auto["_id"], {"enabled": False})).mutation_applied is False
    assert all(r.method == "get" for r in connection.requests)


@pytest.mark.asyncio
async def test_delete_present_after_ack_is_not_success():
    stored = deepcopy(DNS_REDIRECT)
    manager, connection = _manager([stored], {}, [stored])
    result = await manager.delete_nat_rule_verified(stored["_id"])
    assert result.success is False and result.mutation_applied is False
    assert [r.method for r in connection.requests] == ["get", "delete", "get"]


@pytest.mark.asyncio
@pytest.mark.parametrize("method,verb", [("post", "create"), ("put", "update"), ("delete", "delete")])
async def test_legacy_mutation_errors_use_safe_infinitive(method, verb):
    manager, connection = _manager([DNS_REDIRECT], error=RuntimeError("private-controller-value"), fail_on=method)
    with pytest.raises(UniFiOperationError) as error:
        if method == "post":
            await manager.create_nat_rule({**_new_rule(), "rule_index": 1})
        elif method == "put":
            await manager.update_nat_rule(DNS_REDIRECT["_id"], {"description": "after"})
        else:
            await manager.delete_nat_rule(DNS_REDIRECT["_id"])
    assert f"Failed to {verb} NAT rule" in str(error.value)
    assert "private-controller-value" not in str(error.value)
    assert len([request for request in connection.requests if request.method == method]) == 1
