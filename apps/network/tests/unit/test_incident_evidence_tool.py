"""Registration, argument validation and Core delegation for the Network incident evidence tool."""

import ast
import json
from pathlib import Path
from unittest.mock import MagicMock

import jsonschema
import pytest

from unifi_core.incident_evidence import validate_incident_evidence
from unifi_core.source_page import SourcePage

ROOT = Path(__file__).resolve().parents[4]
SCHEMA = json.loads((ROOT / "tests/fixtures/incident_evidence/incident-evidence.v1.schema.json").read_text())
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
    result = await module.get_incident_evidence(**WINDOW, location_id="fixture-location-a", max_calls=3)
    assert result["success"] is True
    document = result["data"]
    jsonschema.validate(document, SCHEMA)
    validate_incident_evidence(document)
    source = document["sources"][0]
    assert source["scope"] == {"controller_id": None, "site": "default", "location_id": "fixture-location-a"}
    assert document["budgets"]["limits"]["calls"] == 3
    assert [record["provenance"]["source_record_id"] for record in document["records"]] == ["evt-1"]


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
async def test_unexpected_failures_return_the_operation_and_class_only(tool, monkeypatch):
    module, _ = tool

    async def broken(*_, **__):
        raise RuntimeError("fixture-private-controller-text")

    monkeypatch.setattr(module, "collect_network_incident_evidence", broken)
    result = await module.get_incident_evidence(**WINDOW)
    assert result == {"success": False, "error": "Failed to collect incident evidence: RuntimeError"}
