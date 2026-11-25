"""System log reads: query parameters, event text and the checks that keep a bad filter from reading as empty."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from unifi_core.drive.managers.log_manager import DriveLogManager
from unifi_core.drive.models.logs import DriveLogQuery, log_entry_from_api, render_message
from unifi_core.exceptions import UniFiMalformedResponseError, UniFiOperationError, UniFiValidationError

from tests.drive import fixtures as fx

LOGS = "/proxy/drive/api/v2/systems/logs"
DEFINITIONS = "/proxy/drive/api/v2/systems/log-definitions"


@pytest.fixture
def log_manager(connection):
    return DriveLogManager(connection)


async def test_entries_carry_event_text_and_drop_identifiers(log_manager, console):
    console.reply("GET", DEFINITIONS, fx.log_definitions())
    console.reply("GET", LOGS, fx.logs())

    page = await log_manager.list_logs()

    first, risk, inserted = (entry.model_dump(exclude_none=True) for entry in page.entries)
    assert first == {
        "time": "2026-11-25T08:35:06.741745-05:00",
        "severity": "low",
        "category": "activity",
        "type": "userAccess",
        "event": "UniFiDriveAccessedDirect",
        "title": "UniFi Drive Accessed",
        "message": "synthetic-user accessed UniFi Drive from 192.0.2.5(Other OS).",
    }
    assert risk["severity"] == "very_high"
    assert risk["message"] == "Storage Pool 1 is degraded. Bay 3 is showing pre-failure indicators."
    assert inserted["event"] == "DriveInserted"
    assert page.next_cursor is None
    dumped = str([entry.model_dump() for entry in page.entries])
    assert "44444444" not in dumped and "55555555" not in dumped
    assert console.calls("GET", LOGS)[0].query == {"limit": "50"}


async def test_filters_become_query_parameters(log_manager, console):
    console.reply("GET", DEFINITIONS, fx.log_definitions())
    console.reply("GET", LOGS, fx.logs(next_token="AAZh+/x="))
    query = DriveLogQuery(
        limit=10,
        severities=["medium", "very_high"],
        types=["storagePool"],
        keyword=" Bay ",
        scope="all",
        after=datetime(2026, 11, 1, tzinfo=timezone.utc),
        before="2026-11-02T00:00:00Z",
        cursor="AAZh+/w=",
    )

    page = await log_manager.list_logs(query)

    assert page.next_cursor == "AAZh+/x="
    assert console.calls("GET", LOGS)[0].query == {
        "limit": "10",
        "severities": "medium,very_high",
        "types": "storagePool",
        "keywords": "Bay",
        "scope": "all",
        "after": "1793491200",
        "before": "1793577600",
        "nextToken": "AAZh+/w=",
    }


async def test_category_sends_its_types(log_manager, console):
    console.reply("GET", DEFINITIONS, fx.log_definitions())
    console.reply("GET", LOGS, fx.logs())

    await log_manager.list_logs(DriveLogQuery(category="storage"))

    assert console.calls("GET", LOGS)[0].query["types"] == "storagePool,drive"


async def test_types_narrow_a_category(log_manager, console):
    console.reply("GET", DEFINITIONS, fx.log_definitions())
    console.reply("GET", LOGS, fx.logs())

    await log_manager.list_logs(DriveLogQuery(category="storage", types=["drive"]))

    assert console.calls("GET", LOGS)[0].query["types"] == "drive"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (DriveLogQuery(category="hardware"), "Unknown log category 'hardware'"),
        (DriveLogQuery(types=["storagePool", "bogus"]), "Unknown log type 'bogus'"),
        (DriveLogQuery(category="activity", types=["drive"]), "not in category 'activity'"),
    ],
)
async def test_unknown_filters_are_refused_not_empty(log_manager, console, query, expected):
    console.reply("GET", DEFINITIONS, fx.log_definitions())

    with pytest.raises(UniFiValidationError, match=expected):
        await log_manager.list_logs(query)

    assert console.calls("GET", LOGS) == []


async def test_category_without_types_reads_nothing(log_manager, console):
    definitions = fx.log_definitions()
    definitions["categoryTypes"]["settings"] = []
    console.reply("GET", DEFINITIONS, definitions)

    page = await log_manager.list_logs(DriveLogQuery(category="settings"))

    assert page.entries == [] and console.calls("GET", LOGS) == []


async def test_missing_endpoint_is_an_error(log_manager, console):
    console.reply("GET", DEFINITIONS, fx.log_definitions())
    console.reply("GET", LOGS, {"err": {"msg": "not found"}}, status=404)

    with pytest.raises(UniFiOperationError, match="no endpoint"):
        await log_manager.list_logs()


@pytest.mark.parametrize("body", [{"logs": None}, {}, []])
async def test_unreadable_log_is_not_empty(log_manager, console, body):
    console.reply("GET", DEFINITIONS, fx.log_definitions())
    console.reply("GET", LOGS, body)

    with pytest.raises(UniFiMalformedResponseError):
        await log_manager.list_logs()


async def test_unreadable_definitions_are_an_error(log_manager, console):
    console.reply("GET", DEFINITIONS, {"events": []})

    with pytest.raises(UniFiMalformedResponseError):
        await log_manager.list_logs()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0},
        {"limit": 501},
        {"severities": ["critical"]},
        {"scope": "everything"},
        {"after": "2026-11-01T00:00:00"},
        {"after": "2026-11-02T00:00:00Z", "before": "2026-11-01T00:00:00Z"},
        {"keyword": "x" * 201},
        {"unexpected": True},
    ],
)
def test_query_validation(kwargs):
    with pytest.raises(ValidationError):
        DriveLogQuery(**kwargs)


def test_blank_filters_are_unset():
    query = DriveLogQuery(keyword="  ", category="", severities=[], types=[], cursor="")
    assert (query.keyword, query.category, query.severities, query.types, query.cursor) == (None,) * 5


def test_message_keeps_placeholders_it_cannot_fill():
    assert render_message("{a} and {b} and {c}", {"a": 2, "b": ["x", "y"], "c": {"nested": 1}}) == (
        "2 and x, y and {c}"
    )
    assert render_message(None, {"a": "x"}) is None


def test_legacy_text_wins_and_unknown_events_have_no_message():
    legacy = log_entry_from_api(
        {"name": "DriveInsertedV1", "legacy": {"title": "Old", "description": "Old {drive}"}, "data": {"drive": "B"}},
        fx.log_definitions()["events"],
    )
    assert (legacy.title, legacy.message) == ("Old", "Old B")
    unknown = log_entry_from_api({"name": "SomethingNewV2", "severity": "low"}, {})
    assert (unknown.event, unknown.title, unknown.message) == ("SomethingNew", None, None)
