"""Tests for the IPS signature suppression read."""

from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.network.managers.system_manager import SystemManager
from unifi_core.network.models.ips_suppression import ips_suppressions_from_controller

# Shape recorded from GET /get/setting/ips_suppression on Network 11.0; values are synthetic.
RECORD = {
    "_id": "603e85e1bcf86cd799439003",
    "key": "ips_suppression",
    "site_id": "603e85e1bcf86cd799439004",
    "alerts": [
        {
            "id": 2000001,
            "gid": 1,
            "type": "track",
            "category": "emerging-scan",
            "signature": "ET TEST Example signature",
            "tracking": [
                {"mode": "ip", "value": "192.0.2.10", "direction": "both"},
                {"mode": "subnet", "value": "192.0.2.128/25", "direction": "src"},
                {"mode": "ip", "value": "192.0.2.20", "direction": "dest"},
            ],
        },
        {"id": 4294967295, "gid": 1, "type": "all", "category": "emerging-misc", "signature": "ET TEST Global"},
    ],
    "whitelist": [{"mode": "ip", "value": "192.0.2.30", "direction": "src"}],
}


def _track(**fields):
    return {"id": 2000001, "type": "track", **fields}


def test_each_tracking_entry_and_global_suppression_is_one_entry():
    tracked = {
        "signature_id": 2000001,
        "gid": 1,
        "signature": "ET TEST Example signature",
        "category": "emerging-scan",
        "suppression_type": "track",
    }
    assert ips_suppressions_from_controller(deepcopy(RECORD)).model_dump() == {
        "suppressions": [
            {**tracked, "scope": "both", "direction": "both", "mode": "ip", "target": "192.0.2.10"},
            {**tracked, "scope": "source", "direction": "src", "mode": "subnet", "target": "192.0.2.128/25"},
            {**tracked, "scope": "destination", "direction": "dest", "mode": "ip", "target": "192.0.2.20"},
            {
                "signature_id": 4294967295,
                "gid": 1,
                "signature": "ET TEST Global",
                "category": "emerging-misc",
                "suppression_type": "all",
                "scope": "global",
                "direction": None,
                "mode": None,
                "target": None,
            },
        ],
        "exclusions": [{"scope": "source", "direction": "src", "mode": "ip", "target": "192.0.2.30"}],
    }


def test_empty_lists_are_a_known_empty_result():
    result = ips_suppressions_from_controller({"key": "ips_suppression", "alerts": [], "whitelist": []})
    assert result.model_dump() == {"suppressions": [], "exclusions": []}


def test_global_type_ignores_leftover_tracking():
    alert = {"id": 2000001, "type": "all", "tracking": [{"mode": "ip", "value": "192.0.2.1", "direction": "src"}]}
    [entry] = ips_suppressions_from_controller({"alerts": [alert], "whitelist": []}).suppressions
    assert (entry.scope, entry.target) == ("global", None)


@pytest.mark.parametrize(
    "alert,direction",
    [
        (_track(tracking=[]), None),
        (_track(), None),
        (_track(tracking=[{"mode": "ip", "value": "192.0.2.1", "direction": "sideways"}]), "sideways"),
        ({"id": 2000001, "type": "future"}, None),
    ],
)
def test_unknown_scope_is_kept_without_guessing(alert, direction):
    [entry] = ips_suppressions_from_controller({"alerts": [alert], "whitelist": []}).suppressions
    assert entry.scope is None
    assert entry.direction == direction


@pytest.mark.parametrize(
    "record",
    [
        None,
        {},
        {"alerts": []},
        {"whitelist": []},
        {"alerts": {}, "whitelist": []},
        {"alerts": ["bad"], "whitelist": []},
        {"alerts": [{"type": "all"}], "whitelist": []},
        {"alerts": [{"id": True, "type": "all"}], "whitelist": []},
        {"alerts": [_track(tracking={})], "whitelist": []},
        {"alerts": [_track(tracking=["bad"])], "whitelist": []},
        {"alerts": [], "whitelist": ["bad"]},
        # A target with no readable address must not look like an entry without one.
        {"alerts": [_track(tracking=[{"mode": "ip", "direction": "both"}])], "whitelist": []},
        {"alerts": [_track(tracking=[{"mode": "ip", "value": 7, "direction": "both"}])], "whitelist": []},
        {"alerts": [], "whitelist": [{"mode": "ip", "direction": "src"}]},
    ],
)
def test_unreadable_records_fail_instead_of_looking_empty(record):
    with pytest.raises(ValueError):
        ips_suppressions_from_controller(record)


@pytest.mark.parametrize("gid", [True, "1", 1.5])
def test_untyped_metadata_is_null_not_coerced(gid):
    alert = {"id": 2000001, "type": "all", "gid": gid, "signature": 7, "category": ["x"]}
    [entry] = ips_suppressions_from_controller({"alerts": [alert], "whitelist": []}).suppressions
    assert (entry.gid, entry.signature, entry.category) == (None, None, None)


def _manager(response):
    connection = MagicMock()
    connection.site = "default"
    connection.request = AsyncMock(return_value=response)
    return SystemManager(connection), connection


@pytest.mark.asyncio
async def test_manager_reads_the_section_fresh():
    manager, connection = _manager([deepcopy(RECORD)])
    result = await manager.list_ips_suppressions()
    assert len(result.suppressions) == 4
    request = connection.request.await_args.args[0]
    assert (request.method, request.path) == ("get", "/get/setting/ips_suppression")
    connection.get_cached.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [[], None, {}, [{}], [RECORD, RECORD]])
async def test_manager_never_reports_an_unavailable_section_as_empty(response):
    manager, _ = _manager(response)
    with pytest.raises(RuntimeError, match="Failed to read IPS suppressions"):
        await manager.list_ips_suppressions()


@pytest.mark.asyncio
async def test_manager_error_does_not_echo_the_controller(caplog):
    manager, connection = _manager(None)
    connection.request.side_effect = RuntimeError("private controller text")
    with pytest.raises(RuntimeError) as caught:
        await manager.list_ips_suppressions()
    assert "private controller text" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True
    assert "private controller text" not in caplog.text
