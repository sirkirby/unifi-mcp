"""Tests for creating and deleting IPS signature suppressions."""

from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.managers.connection_manager import SettingsControllerRejection
from unifi_core.network.managers.system_manager import SystemManager
from unifi_core.network.models.ips_suppression import (
    IpsSuppressionConflict,
    IpsSuppressionCreate,
    IpsSuppressionDelete,
    apply_suppression_create,
    apply_suppression_delete,
)

# Shape recorded from GET /get/setting/ips_suppression on Network 11.0; values are synthetic.
TRACKED = {
    "id": 2000001,
    "gid": 1,
    "type": "track",
    "category": "emerging-scan",
    "signature": "ET TEST Example signature",
    "tracking": [
        {"mode": "ip", "value": "192.0.2.10", "direction": "both"},
        {"mode": "subnet", "value": "192.0.2.128/25", "direction": "src"},
    ],
}
GLOBAL = {
    "id": 2000002,
    "gid": 1,
    "type": "all",
    "category": "emerging-misc",
    "signature": "ET TEST Global",
    "tracking": [{"mode": "ip", "value": "192.0.2.40", "direction": "both"}],
}
RECORD = {
    "_id": "603e85e1bcf86cd799439003",
    "key": "ips_suppression",
    "site_id": "603e85e1bcf86cd799439004",
    "alerts": [TRACKED, GLOBAL],
    "whitelist": [{"mode": "ip", "value": "192.0.2.30", "direction": "src"}],
}


def _create(**fields):
    return IpsSuppressionCreate(**{"signature_id": 2000009, "scope": "both", "target": "192.0.2.50", **fields})


def _others_untouched(before, after, signature_id):
    assert {k: v for k, v in after.items() if k != "alerts"} == {k: v for k, v in before.items() if k != "alerts"}
    assert [a for a in after["alerts"] if a["id"] != signature_id] == [
        a for a in before["alerts"] if a["id"] != signature_id
    ]


# --- input models ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("target", "entry"),
    [
        ("192.0.2.50", {"mode": "ip", "value": "192.0.2.50"}),
        (" 192.0.2.50 ", {"mode": "ip", "value": "192.0.2.50"}),
        ("192.0.2.0/28", {"mode": "subnet", "value": "192.0.2.0/28"}),
        ("2001:DB8::1", {"mode": "ip", "value": "2001:db8::1"}),
        ("2001:db8::/32", {"mode": "subnet", "value": "2001:db8::/32"}),
    ],
)
def test_a_target_becomes_an_ip_or_subnet_entry(target, entry):
    assert _create(target=target, scope="destination").tracking_entry() == {**entry, "direction": "dest"}


@pytest.mark.parametrize("scope,direction", [("source", "src"), ("destination", "dest"), ("both", "both")])
def test_each_scope_is_the_controllers_direction(scope, direction):
    assert _create(scope=scope).tracking_entry()["direction"] == direction


@pytest.mark.parametrize(
    "fields",
    [
        {"scope": "both", "target": None},
        {"scope": "global", "target": "192.0.2.50"},
        {"target": "192.0.2.1/24"},
        {"target": "not-an-address"},
        {"target": "192.0.2.300"},
        {"signature_id": True},
        {"signature_id": "2000009"},
        {"signature_id": 0},
        {"gid": 0},
        {"scope": "everything"},
        {"category": "x" * 129},
        {"comment": "extra"},
    ],
)
def test_create_refuses_bad_input(fields):
    with pytest.raises(ValidationError):
        _create(**fields)


@pytest.mark.parametrize(
    "fields",
    [{"scope": "both"}, {"target": "bad"}, {"signature_id": False}, {"target": "192.0.2.1/24"}, {"why": 1}],
)
def test_delete_refuses_bad_input(fields):
    with pytest.raises(ValidationError):
        IpsSuppressionDelete(**{"signature_id": 2000001, **fields})


# --- create -----------------------------------------------------------------------------------


def test_create_adds_a_targeted_suppression_for_a_new_signature():
    after = apply_suppression_create(RECORD, _create(signature="ET TEST New", category="emerging-webapps"))
    assert after["alerts"][-1] == {
        "id": 2000009,
        "gid": 1,
        "signature": "ET TEST New",
        "category": "emerging-webapps",
        "type": "track",
        "tracking": [{"mode": "ip", "value": "192.0.2.50", "direction": "both"}],
    }
    _others_untouched(RECORD, after, 2000009)
    assert RECORD["alerts"] == [TRACKED, GLOBAL]  # the input is not mutated


def test_create_without_a_name_or_category_stores_neither():
    alert = apply_suppression_create(RECORD, _create())["alerts"][-1]
    assert "signature" not in alert and "category" not in alert


def test_create_adds_a_global_suppression_for_a_new_signature():
    alert = apply_suppression_create(RECORD, _create(scope="global", target=None))["alerts"][-1]
    assert (alert["type"], alert["tracking"]) == ("all", [])


def test_create_merges_a_target_into_the_signatures_alert():
    after = apply_suppression_create(RECORD, _create(signature_id=2000001, target="192.0.2.60", scope="source"))
    assert len(after["alerts"]) == 2
    assert after["alerts"][0]["tracking"][-1] == {"mode": "ip", "value": "192.0.2.60", "direction": "src"}
    assert after["alerts"][0]["signature"] == TRACKED["signature"]
    _others_untouched(RECORD, after, 2000001)


def test_create_keeps_the_stored_name_and_category():
    after = apply_suppression_create(
        RECORD, _create(signature_id=2000001, target="192.0.2.60", signature="Other", category="emerging-dos")
    )
    assert (after["alerts"][0]["signature"], after["alerts"][0]["category"]) == (
        TRACKED["signature"],
        TRACKED["category"],
    )


def test_a_target_already_suppressed_changes_nothing():
    assert apply_suppression_create(RECORD, _create(signature_id=2000001, target="192.0.2.10")) == RECORD


def test_the_same_target_in_another_direction_is_another_entry():
    after = apply_suppression_create(RECORD, _create(signature_id=2000001, target="192.0.2.10", scope="source"))
    assert len(after["alerts"][0]["tracking"]) == 3


def test_create_makes_a_targeted_suppression_global_and_keeps_its_targets():
    after = apply_suppression_create(RECORD, _create(signature_id=2000001, scope="global", target=None))
    assert after["alerts"][0]["type"] == "all"
    assert after["alerts"][0]["tracking"] == TRACKED["tracking"]


def test_a_global_suppression_already_in_place_changes_nothing():
    assert apply_suppression_create(RECORD, _create(signature_id=2000002, scope="global", target=None)) == RECORD


def test_a_target_for_a_globally_suppressed_signature_is_a_conflict():
    with pytest.raises(IpsSuppressionConflict, match="already suppressed for all traffic"):
        apply_suppression_create(RECORD, _create(signature_id=2000002))


@pytest.mark.parametrize("global_first", [True, False])
def test_a_global_duplicate_in_either_order_makes_a_target_a_conflict(global_first):
    record = deepcopy(RECORD)
    duplicate = {**deepcopy(GLOBAL), "id": TRACKED["id"]}
    record["alerts"] = [duplicate, deepcopy(TRACKED)] if global_first else [deepcopy(TRACKED), duplicate]
    with pytest.raises(IpsSuppressionConflict):
        apply_suppression_create(record, _create(signature_id=TRACKED["id"]))


def test_a_target_held_by_a_duplicate_alert_changes_nothing():
    record = deepcopy(RECORD)
    record["alerts"].append(
        {**deepcopy(TRACKED), "tracking": [{"mode": "ip", "value": "192.0.2.70", "direction": "both"}]}
    )
    assert apply_suppression_create(record, _create(signature_id=TRACKED["id"], target="192.0.2.70")) == record


def test_making_a_signature_global_marks_every_duplicate():
    record = deepcopy(RECORD)
    record["alerts"].append(deepcopy(TRACKED))
    after = apply_suppression_create(record, _create(signature_id=TRACKED["id"], scope="global", target=None))
    assert [a["type"] for a in after["alerts"] if a["id"] == TRACKED["id"]] == ["all", "all"]


def test_the_generator_id_tells_signatures_apart():
    after = apply_suppression_create(RECORD, _create(signature_id=2000001, gid=3))
    assert len(after["alerts"]) == 3 and after["alerts"][-1]["gid"] == 3


# --- delete -----------------------------------------------------------------------------------


def _delete(**fields):
    return IpsSuppressionDelete(**{"signature_id": 2000001, **fields})


def test_delete_without_a_target_removes_the_whole_suppression():
    after = apply_suppression_delete(RECORD, _delete())
    assert [a["id"] for a in after["alerts"]] == [2000002]
    assert after["whitelist"] == RECORD["whitelist"]


def test_delete_removes_a_global_suppression():
    assert [a["id"] for a in apply_suppression_delete(RECORD, _delete(signature_id=2000002))["alerts"]] == [2000001]


def test_delete_removes_every_duplicate_alert_of_the_signature():
    record = deepcopy(RECORD)
    record["alerts"].append(
        {**deepcopy(TRACKED), "tracking": [{"mode": "ip", "value": "192.0.2.70", "direction": "both"}]}
    )
    assert [a["id"] for a in apply_suppression_delete(record, _delete())["alerts"]] == [2000002]


def test_delete_removes_one_target_and_keeps_the_rest():
    after = apply_suppression_delete(RECORD, _delete(target="192.0.2.10"))
    assert after["alerts"][0]["tracking"] == [TRACKED["tracking"][1]]
    _others_untouched(RECORD, after, 2000001)


def test_a_scope_only_removes_the_target_in_that_direction():
    with pytest.raises(UniFiNotFoundError):
        apply_suppression_delete(RECORD, _delete(target="192.0.2.0/25", scope="destination"))
    after = apply_suppression_delete(RECORD, _delete(target="192.0.2.128/25", scope="source"))
    assert after["alerts"][0]["tracking"] == [TRACKED["tracking"][0]]


def test_removing_the_last_target_removes_the_suppression():
    record = deepcopy(RECORD)
    record["alerts"][0]["tracking"] = record["alerts"][0]["tracking"][:1]
    assert [a["id"] for a in apply_suppression_delete(record, _delete(target="192.0.2.10"))["alerts"]] == [2000002]


@pytest.mark.parametrize(
    "request_fields", [{"signature_id": 2999999}, {"gid": 3}, {"target": "192.0.2.99"}, {"target": "192.0.2.10/32"}]
)
def test_what_is_not_suppressed_is_not_found(request_fields):
    with pytest.raises(UniFiNotFoundError):
        apply_suppression_delete(RECORD, _delete(**request_fields))


def test_a_target_of_a_global_suppression_is_a_conflict():
    with pytest.raises(IpsSuppressionConflict, match="omit target"):
        apply_suppression_delete(RECORD, _delete(signature_id=2000002, target="192.0.2.40"))


# --- manager ----------------------------------------------------------------------------------


def _manager(*responses, session=True):
    connection = MagicMock()
    connection.site = "default"
    connection.request = AsyncMock(side_effect=list(responses))
    connection.ensure_session_connected = AsyncMock(return_value=session)
    return SystemManager(connection), connection


def _posts(connection):
    return [c.args[0] for c in connection.request.await_args_list if c.args[0].method == "post"]


@pytest.mark.asyncio
async def test_create_posts_the_whole_section_once_and_verifies_it():
    wanted = apply_suppression_create(RECORD, _create())
    manager, connection = _manager([deepcopy(RECORD)], [], [deepcopy(wanted)])
    result = await manager.create_ips_suppression(_create())
    [post] = _posts(connection)
    assert (post.path, post.data) == ("/set/setting/ips_suppression", wanted)
    assert post.data["_id"] == RECORD["_id"] and post.data["whitelist"] == RECORD["whitelist"]
    assert (result.success, result.mutation_applied, result.persisted_fields) == (True, True, ("suppressions",))
    assert result.resource["suppressions"][0]["target"] == "192.0.2.50"
    connection._invalidate_cache.assert_called_once()


@pytest.mark.asyncio
async def test_delete_verifies_the_signature_is_gone():
    wanted = apply_suppression_delete(RECORD, _delete())
    manager, connection = _manager([deepcopy(RECORD)], [], [deepcopy(wanted)])
    result = await manager.delete_ips_suppression(_delete())
    assert result.success and result.persisted_fields == ("suppressions",)
    assert result.resource == {"suppressions": []}


@pytest.mark.asyncio
async def test_a_change_already_in_place_sends_nothing():
    manager, connection = _manager([deepcopy(RECORD)])
    result = await manager.create_ips_suppression(_create(signature_id=2000001, target="192.0.2.10"))
    assert (result.success, result.mutation_applied) == (True, False)
    assert _posts(connection) == []


@pytest.mark.asyncio
async def test_a_controller_that_kept_the_old_section_is_a_failed_write():
    manager, _ = _manager([deepcopy(RECORD)], [], [deepcopy(RECORD)])
    result = await manager.create_ips_suppression(_create())
    assert result.success is False and result.dropped_fields == ("suppressions",)


@pytest.mark.asyncio
async def test_a_rejected_write_names_only_the_controller_code():
    manager, _ = _manager([deepcopy(RECORD)], SettingsControllerRejection("api.err.InvalidPayload"))
    result = await manager.create_ips_suppression(_create(category="not-a-category"))
    assert (result.success, result.mutation_applied) == (False, False)
    assert "api.err.InvalidPayload" in result.error and "not-a-category" not in result.error


@pytest.mark.asyncio
async def test_a_lost_answer_is_an_uncertain_outcome():
    manager, _ = _manager([deepcopy(RECORD)], ConnectionError("reset"))
    result = await manager.delete_ips_suppression(_delete())
    assert (result.success, result.mutation_applied) == (False, None)
    assert result.to_dict()["outcome_uncertain"] is True


@pytest.mark.asyncio
async def test_a_failed_readback_is_an_uncertain_outcome():
    manager, _ = _manager([deepcopy(RECORD)], [], RuntimeError("gone"))
    result = await manager.delete_ips_suppression(_delete())
    assert (result.success, result.mutation_applied) == (False, None)


@pytest.mark.asyncio
async def test_preview_shows_the_signature_before_and_after_and_never_writes():
    manager, connection = _manager([deepcopy(RECORD)])
    preview = await manager.preview_ips_suppression_change(_delete(target="192.0.2.10"))
    assert [e["target"] for e in preview["current"]] == ["192.0.2.10", "192.0.2.128/25"]
    assert [e["target"] for e in preview["after"]] == ["192.0.2.128/25"]
    assert _posts(connection) == []


@pytest.mark.asyncio
async def test_conflicts_and_missing_suppressions_fail_before_any_write():
    manager, connection = _manager([deepcopy(RECORD)], [deepcopy(RECORD)])
    with pytest.raises(IpsSuppressionConflict):
        await manager.create_ips_suppression(_create(signature_id=2000002))
    with pytest.raises(UniFiNotFoundError):
        await manager.delete_ips_suppression(_delete(signature_id=2999999))
    assert _posts(connection) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("session", [False, ConnectionError("no session")])
async def test_without_a_network_session_nothing_is_read_or_sent(session):
    manager, connection = _manager([deepcopy(RECORD)])
    if isinstance(session, Exception):
        connection.ensure_session_connected = AsyncMock(side_effect=session)
    else:
        connection.ensure_session_connected = AsyncMock(return_value=session)
    for call in (
        manager.create_ips_suppression(_create()),
        manager.delete_ips_suppression(_delete()),
        manager.preview_ips_suppression_change(_create()),
    ):
        with pytest.raises(RuntimeError, match="requires Network session authentication"):
            await call
    connection.request.assert_not_awaited()
