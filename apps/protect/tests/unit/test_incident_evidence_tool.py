"""Registration, argument validation and Core delegation for the Protect incident evidence tool."""

import ast
import json
from pathlib import Path

import jsonschema
import pytest

from unifi_core.incident_evidence import validate_incident_evidence
from unifi_core.source_page import SourcePage

ROOT = Path(__file__).resolve().parents[4]
SCHEMA = json.loads((ROOT / "tests/fixtures/incident_evidence/incident-evidence.v1.schema.json").read_text())
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
    return incident_evidence, pages


def test_tool_is_registered_read_only_and_listed_directly_in_lazy_mode():
    from unifi_protect_mcp.categories import LAZY_DIRECT_TOOLS, TOOL_MODULE_MAP
    from unifi_protect_mcp.runtime import server
    from unifi_protect_mcp.tools import incident_evidence  # noqa: F401 - decorator registration

    tool = server._tool_manager._tools["protect_get_incident_evidence"]
    assert tool.annotations.read_only_hint is True and tool.annotations.open_world_hint is False
    assert "protect_get_incident_evidence" in LAZY_DIRECT_TOOLS
    assert TOOL_MODULE_MAP["protect_get_incident_evidence"] == "unifi_protect_mcp.tools.incident_evidence"


def test_direct_tool_modules_hold_nothing_but_direct_tools():
    """Lazy mode registers every tool in a direct tool's module, so nothing else may live there."""
    from unifi_protect_mcp.categories import LAZY_DIRECT_TOOLS, TOOL_MODULE_MAP

    for module in {TOOL_MODULE_MAP[name] for name in LAZY_DIRECT_TOOLS}:
        path = ROOT / "apps/protect/src" / (module.replace(".", "/") + ".py")
        names = {
            keyword.value.value
            for node in ast.walk(ast.parse(path.read_text()))
            if isinstance(node, ast.Call)
            for keyword in node.keywords
            if keyword.arg == "name" and isinstance(keyword.value, ast.Constant)
        }
        assert names <= set(LAZY_DIRECT_TOOLS)


@pytest.mark.asyncio
async def test_each_camera_is_a_source_in_a_contract_valid_document(tool):
    module, pages = tool
    pages.rows = [{"id": "evt-1", "type": "motion", "camera": CAMERA, "start": 1786191000000}]
    result = await module.get_incident_evidence(**WINDOW, camera_ids=["cam-fixture-000b", CAMERA])
    assert result["success"] is True
    document = result["data"]
    jsonschema.validate(document, SCHEMA)
    validate_incident_evidence(document)
    assert [(s["source_id"], s["coverage"]["filters"]) for s in document["sources"]] == [
        ("protect.events.camera.01", {"camera_id": CAMERA}),
        ("protect.events.camera.02", {"camera_id": "cam-fixture-000b"}),
    ]
    assert [call[0] for call in pages.calls] == [CAMERA, "cam-fixture-000b"]


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
