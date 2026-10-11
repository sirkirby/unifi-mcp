"""Registration, argument validation and Core delegation for the Network incident evidence tool."""

import ast
import json
from pathlib import Path
from unittest.mock import MagicMock

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
DEVICE = "02:00:00:00:00:0a"


class EventPages:
    def __init__(self, rows=(), error=None):
        self.rows, self.error, self.calls = list(rows), error, []

    async def read_events_page(self, *, within, limit, offset=0, window_ms=None):
        self.calls.append((within, limit, offset))
        if self.error:
            raise self.error
        rows = self.rows[offset : offset + limit]
        return SourcePage(rows=rows, total_reported=len(self.rows), offset=offset, cap=limit, api_path="v2")


@pytest.fixture
def tool(monkeypatch):
    from unifi_network_mcp import runtime
    from unifi_network_mcp.tools import incident_evidence

    pages = EventPages()
    connection = MagicMock()
    connection.site = "default"
    monkeypatch.setattr(runtime, "get_event_manager", lambda: pages)
    monkeypatch.setattr(runtime, "get_connection_manager", lambda: connection)
    return incident_evidence, pages


def test_tool_is_registered_read_only_and_listed_directly_in_lazy_mode():
    from unifi_network_mcp.categories import LAZY_DIRECT_TOOLS, TOOL_MODULE_MAP
    from unifi_network_mcp.runtime import server
    from unifi_network_mcp.tools import incident_evidence  # noqa: F401 - decorator registration

    tool = server._tool_manager._tools["unifi_get_incident_evidence"]
    assert tool.annotations.read_only_hint is True and tool.annotations.open_world_hint is False
    assert "unifi_get_incident_evidence" in LAZY_DIRECT_TOOLS
    assert TOOL_MODULE_MAP["unifi_get_incident_evidence"] == "unifi_network_mcp.tools.incident_evidence"


def test_direct_tool_modules_hold_nothing_but_direct_tools():
    """Lazy mode registers every tool in a direct tool's module, so nothing else may live there."""
    from unifi_network_mcp.categories import LAZY_DIRECT_TOOLS, TOOL_MODULE_MAP

    for module in {TOOL_MODULE_MAP[name] for name in LAZY_DIRECT_TOOLS}:
        path = ROOT / "apps/network/src" / (module.replace(".", "/") + ".py")
        names = {
            keyword.value.value
            for node in ast.walk(ast.parse(path.read_text()))
            if isinstance(node, ast.Call)
            for keyword in node.keywords
            if keyword.arg == "name" and isinstance(keyword.value, ast.Constant)
        }
        assert names <= set(LAZY_DIRECT_TOOLS)


@pytest.mark.asyncio
async def test_returns_a_contract_valid_document_scoped_to_the_site(tool):
    module, pages = tool
    pages.rows = [
        {
            "id": "evt-1",
            "key": "DEVICE_DISCONNECTED_AP",
            "timestamp": 1786191000000,
            "parameters": {"DEVICE": {"id": DEVICE}},
        }
    ]
    result = await module.get_incident_evidence(**WINDOW, location_id="fixture-location-a", max_calls=3, detail="full")
    assert result["success"] is True
    document = result["data"]
    jsonschema.validate(document, SCHEMA)
    validate_incident_evidence(document)
    source = document["sources"][0]
    assert source["scope"] == {"controller_id": None, "site": "default", "location_id": "fixture-location-a"}
    assert document["budgets"]["limits"]["calls"] == 3
    assert [record["provenance"]["source_record_id"] for record in document["records"]] == ["evt-1"]


@pytest.mark.asyncio
async def test_returns_the_bounded_view_of_the_same_document_by_default(tool):
    module, pages = tool
    pages.rows = [{"id": f"evt-{i}", "key": "DEVICE_DISCONNECTED_AP", "timestamp": 1786191000000 + i} for i in range(3)]
    full = await module.get_incident_evidence(**WINDOW, detail="full")
    result = await module.get_incident_evidence(**WINDOW, max_records_returned=2)
    assert result["success"] is True
    view = result["data"]
    jsonschema.validate(view, VIEW_SCHEMA)
    IncidentEvidenceView.model_validate(view)
    expected = view_to_json(client_view(validate_incident_evidence(full["data"]), max_records_returned=2))
    # Two real reads differ only in measured wall time.
    for payload in (view, expected):
        payload["budgets"]["usage"]["elapsed_ms"] = 0
    assert view == expected
    assert view["record_selection"]["omitted"]["in_window"] == 1
    default = await module.get_incident_evidence(**WINDOW)
    assert default["data"]["record_selection"]["max_records_returned"] == 25
    resumed = await module.get_incident_evidence(
        **WINDOW, max_records_returned=2, resume_after=view["record_selection"]["next_cursor"]
    )
    assert resumed["data"]["record_selection"]["before_resume"]["total"] == 2
    assert [record["source_record_id"] for record in resumed["data"]["records"]] == ["evt-2"]


@pytest.mark.asyncio
async def test_source_failures_stay_inside_a_successful_response(tool):
    module, pages = tool
    pages.error = PermissionError("fixture-private-controller-text")
    result = await module.get_incident_evidence(**WINDOW)
    assert result["success"] is True
    assert result["data"]["overall"] == "failed"
    assert result["data"]["sources"][0]["outcome"] == "permission_denied"
    assert "fixture-private-controller-text" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"start": "2026-08-08T12:00:00", "end": WINDOW["end"]}, "explicit UTC offset"),
        ({**WINDOW, "device_macs": ["fixture-ap-1"]}, "device_macs"),
        ({**WINDOW, "max_events": 0}, "max_events"),
        ({**WINDOW, "mappings": [{"entity": "fixture-ap-1"}]}, "mappings"),
        (
            {
                **WINDOW,
                "mappings": [
                    {
                        "entity": {"kind": "network_device", "id_kind": "mac", "id": DEVICE, "fixture-ap-1": "x"},
                        "target": {"kind": "camera", "id_kind": "protect_camera_id", "id": "cam-fixture-000a"},
                        "source": "operator_input",
                    }
                ],
            },
            "mappings.0.entity: Extra inputs are not permitted",
        ),
        ({**WINDOW, "detail": "fixture-ap-1"}, "detail"),
        ({**WINDOW, "max_records_returned": 51}, "max_records_returned"),
        ({**WINDOW, "detail": "full", "max_records_returned": 5}, "apply only to detail=view"),
        ({**WINDOW, "resume_after": "fixture-ap-1"}, "resume_after"),
        ({**WINDOW, "location_id": "fixture-ap-1\n"}, "location_id"),
        (
            {
                **WINDOW,
                "mappings": [
                    {
                        "entity": {"kind": "network_device", "id_kind": "mac", "id": DEVICE},
                        "target": {"kind": "location", "id_kind": "location_id", "id": "fixture-ap-1" * 6},
                        "source": "operator_input",
                    }
                ],
            },
            "mapping identifiers must be 1-64 characters",
        ),
    ],
)
async def test_invalid_arguments_fail_before_any_read_without_echoing_input(tool, arguments, message):
    module, pages = tool
    result = await module.get_incident_evidence(**arguments)
    assert result["success"] is False
    assert result["error"].startswith("Failed to collect incident evidence: ")
    assert message in result["error"]
    assert "fixture-ap-1" not in result["error"]
    assert pages.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("site", ["-" * 30_000, 'fixture-ap-1"', "fixture-ap-1\\", ""])
async def test_a_configured_site_breaking_the_label_rule_is_refused_before_any_read(tool, monkeypatch, site):
    """The configured site is recorded in every source's scope, so it is held to the label rule."""
    from unifi_network_mcp import runtime

    module, pages = tool
    monkeypatch.setattr(runtime, "get_connection_manager", lambda: MagicMock(site=site))
    result = await module.get_incident_evidence(**WINDOW)
    assert result == {
        "success": False,
        "error": "Failed to collect incident evidence: configured site: must be 1-128 characters without control "
        "characters, quotes or backslashes; set UNIFI_NETWORK_SITE to the site's name, for example default",
    }
    assert pages.calls == []


@pytest.mark.asyncio
async def test_evidence_too_broad_for_its_view_is_refused_with_how_to_narrow_it(tool, monkeypatch):
    module, _ = tool
    fixture = json.loads((ROOT / "tests/fixtures/incident_evidence/view-bounds/skeleton_refusal.json").read_text())
    refused = validate_incident_evidence(fixture["evidence"])

    async def collect(*_, **__):
        return refused

    monkeypatch.setattr(module, "collect_network_incident_evidence", collect)
    result = await module.get_incident_evidence(**WINDOW)
    assert result == {"success": False, "error": f"Failed to collect incident evidence: {fixture['refusal']}"}
    assert (await module.get_incident_evidence(**WINDOW, detail="full"))["success"] is True


@pytest.mark.asyncio
async def test_unexpected_failures_return_the_operation_and_class_only(tool, monkeypatch):
    module, _ = tool

    async def broken(*_, **__):
        raise RuntimeError("fixture-private-controller-text")

    monkeypatch.setattr(module, "collect_network_incident_evidence", broken)
    result = await module.get_incident_evidence(**WINDOW)
    assert result == {"success": False, "error": "Failed to collect incident evidence: RuntimeError"}


@pytest.mark.asyncio
async def test_a_long_whitespace_run_is_cut_and_marked_in_the_view(tool):
    """Four million spaces in a controller event cost a token each: the summary is cut and marked, never sent whole."""
    module, pages = tool
    spaces = "A" + " " * 4_000_000 + "B"
    summary = spaces
    pages.rows = [{"id": "evt-1", "key": "DEVICE_DISCONNECTED_AP", "timestamp": 1786191000000, "message_raw": spaces}]
    result = await module.get_incident_evidence(**WINDOW)
    assert result["success"] is True
    (record,) = result["data"]["records"]
    assert record["truncated"] == {"summary": len(summary)}
    assert record["summary"] == summary[: TEXT_TOKEN_LIMITS["summary"]]
    assert estimated_tokens(result) <= VIEW_TOKEN_BUDGET
    assert len(json.dumps(result, ensure_ascii=False, indent=2).encode()) < min(10_000, VIEW_BYTE_LIMIT)
