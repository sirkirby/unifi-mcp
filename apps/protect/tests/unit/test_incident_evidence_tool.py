"""Registration, argument validation and Core delegation for the Protect incident evidence tool."""

import json
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

from unifi_core.incident_evidence import validate_incident_evidence
from unifi_core.incident_evidence_view import (
    TEXT_TOKEN_LIMITS,
    VIEW_BYTE_LIMIT,
    VIEW_TOKEN_BUDGET,
    IncidentEvidenceView,
    client_view,
    estimated_tokens,
    view_to_json,
)
from unifi_core.source_page import SourcePage

ROOT = Path(__file__).resolve().parents[4]
SCHEMA = json.loads((ROOT / "tests/fixtures/incident_evidence/incident-evidence.v1.schema.json").read_text())
VIEW_SCHEMA = json.loads((ROOT / "tests/fixtures/incident_evidence/incident-evidence-view.v1.schema.json").read_text())
WINDOW = {"start": "2026-08-08T12:00:00Z", "end": "2026-08-08T13:00:00Z"}
CAMERA = "cam-fixture-000a"


class EventPages:
    def __init__(self, rows=(), error=None):
        self.rows, self.error, self.calls = list(rows), error, []

    async def list_events_raw_page(self, *, start, end, limit, offset=0, camera_id=None):
        self.calls.append((camera_id, offset, limit))
        if self.error:
            raise self.error
        rows = self.rows[offset : offset + limit]
        return SourcePage(
            rows=rows,
            has_more=False if len(rows) < limit else None,
            offset=offset,
            cap=limit,
            submitted_window_ms=(int(start.timestamp() * 1000), int(end.timestamp() * 1000)),
        )


@pytest.fixture
def tool(monkeypatch):
    from unifi_protect_mcp.tools import incident_evidence

    pages = EventPages()
    monkeypatch.setattr(incident_evidence, "event_manager", pages)
    monkeypatch.setattr(incident_evidence, "connection_manager", SimpleNamespace(client=object()))
    return incident_evidence, pages


def test_tool_is_registered_read_only_and_listed_directly_in_lazy_mode():
    from unifi_protect_mcp.categories import LAZY_DIRECT_TOOLS, TOOL_MODULE_MAP
    from unifi_protect_mcp.runtime import server
    from unifi_protect_mcp.tools import incident_evidence  # noqa: F401 - decorator registration

    tool = server._tool_manager._tools["protect_get_incident_evidence"]
    assert tool.annotations.read_only_hint is True and tool.annotations.open_world_hint is False
    assert "protect_get_incident_evidence" in LAZY_DIRECT_TOOLS
    assert TOOL_MODULE_MAP["protect_get_incident_evidence"] == "unifi_protect_mcp.tools.incident_evidence"


@pytest.mark.asyncio
async def test_each_camera_is_a_source_in_a_contract_valid_document(tool):
    module, pages = tool
    pages.rows = [{"id": "evt-1", "type": "motion", "camera": CAMERA, "start": 1786191000000}]
    result = await module.get_incident_evidence(**WINDOW, camera_ids=["cam-fixture-000b", CAMERA], detail="full")
    assert result["success"] is True
    document = result["data"]
    jsonschema.validate(document, SCHEMA)
    validate_incident_evidence(document)
    view = (await module.get_incident_evidence(**WINDOW, camera_ids=["cam-fixture-000b", CAMERA]))["data"]
    jsonschema.validate(view, VIEW_SCHEMA)
    expected = view_to_json(client_view(validate_incident_evidence(document)))
    # Two real reads differ only in measured wall time.
    for payload in (view, expected):
        payload["budgets"]["usage"]["elapsed_ms"] = 0
    assert view == expected
    assert IncidentEvidenceView.model_validate(view).sources[0].coverage.filters == {"camera_id": CAMERA}
    assert [(s["source_id"], s["coverage"]["filters"]) for s in document["sources"]] == [
        ("protect.events.camera.01", {"camera_id": CAMERA}),
        ("protect.events.camera.02", {"camera_id": "cam-fixture-000b"}),
    ]
    assert [call[0] for call in pages.calls] == [CAMERA, "cam-fixture-000b"] * 2


@pytest.mark.asyncio
async def test_source_failures_stay_inside_a_successful_response(tool):
    module, pages = tool
    pages.error = TimeoutError("fixture-private-controller-text")
    result = await module.get_incident_evidence(**WINDOW)
    assert result["success"] is True
    assert result["data"]["sources"][0]["outcome"] == "timeout"
    assert "fixture-private-controller-text" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"start": "2026-08-08T12:00:00", "end": WINDOW["end"]}, "explicit UTC offset"),
        ({**WINDOW, "camera_ids": ["Front Door"]}, "camera_ids"),
        ({**WINDOW, "max_calls": 1000}, "max_calls"),
        ({**WINDOW, "camera_ids": [f"cam-fixture-{i:04d}" for i in range(6)]}, "camera_ids"),
        ({**WINDOW, "detail": "Front Door"}, "detail"),
        ({**WINDOW, "max_records_returned": 0}, "max_records_returned"),
        ({**WINDOW, "resume_after": "Front Door"}, "resume_after"),
        ({**WINDOW, "detail": "full", "resume_after": "1||protect.events|str|Front"}, "apply only to detail=view"),
    ],
)
async def test_invalid_arguments_fail_before_any_read_without_echoing_input(tool, arguments, message):
    module, pages = tool
    result = await module.get_incident_evidence(**arguments)
    assert result["success"] is False
    assert result["error"].startswith("Failed to collect incident evidence: ")
    assert message in result["error"]
    assert "Front Door" not in result["error"]
    assert pages.calls == []


@pytest.mark.asyncio
async def test_unexpected_failures_return_the_operation_and_class_only(tool, monkeypatch):
    module, _ = tool

    async def broken(*_, **__):
        raise RuntimeError("fixture-private-controller-text")

    monkeypatch.setattr(module, "collect_protect_incident_evidence", broken)
    result = await module.get_incident_evidence(**WINDOW)
    assert result == {"success": False, "error": "Failed to collect incident evidence: RuntimeError"}


@pytest.mark.asyncio
async def test_evidence_too_broad_for_its_view_is_refused_with_how_to_narrow_it(tool, monkeypatch):
    module, _ = tool
    fixture = json.loads((ROOT / "tests/fixtures/incident_evidence/view-bounds/skeleton_refusal.json").read_text())
    refused = validate_incident_evidence(fixture["evidence"])

    async def collect(*_, **__):
        return refused

    monkeypatch.setattr(module, "collect_protect_incident_evidence", collect)
    result = await module.get_incident_evidence(**WINDOW)
    assert result == {"success": False, "error": f"Failed to collect incident evidence: {fixture['refusal']}"}
    assert (await module.get_incident_evidence(**WINDOW, detail="full"))["success"] is True


@pytest.mark.asyncio
async def test_a_long_whitespace_run_is_cut_and_marked_in_the_view(tool):
    """Four million spaces in a controller event cost a token each: the summary is cut and marked, never sent whole."""
    module, pages = tool
    spaces = "A" + " " * 4_000_000 + "B"
    summary = f"motion: {spaces}"
    pages.rows = [
        {"id": "evt-1", "type": "motion", "camera": CAMERA, "start": 1786191000000, "smartDetectTypes": [spaces]}
    ]
    result = await module.get_incident_evidence(**WINDOW, camera_ids=[CAMERA])
    assert result["success"] is True
    (record,) = result["data"]["records"]
    assert record["truncated"] == {"summary": len(summary)}
    assert record["summary"] == summary[: TEXT_TOKEN_LIMITS["summary"]]
    assert estimated_tokens(result) <= VIEW_TOKEN_BUDGET
    assert len(json.dumps(result, ensure_ascii=False, indent=2).encode()) < min(10_000, VIEW_BYTE_LIMIT)
