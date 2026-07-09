"""Tests for live-smoke MCP response size measurements."""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp.types import CallToolResult, TextContent

_script_path = Path(__file__).parent.parent / "scripts" / "live_smoke.py"
_spec = importlib.util.spec_from_file_location("live_smoke", _script_path)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

measure_tool_result_sizes = _mod.measure_tool_result_sizes
LiveSmokeRunner = _mod.LiveSmokeRunner
summarize_payload = _mod.summarize_payload


def test_measure_structured_tuple_sizes_both_payloads():
    payload = {"success": True, "items": [{"id": 1}]}
    raw = ([TextContent(type="text", text=json.dumps(payload))], payload)

    sizes = measure_tool_result_sizes(raw)

    assert sizes["content_bytes"] > 0
    assert sizes["structured_bytes"] > 0
    assert sizes["combined_response_bytes"] == sizes["content_bytes"] + sizes["structured_bytes"]


def test_measure_compact_call_tool_result_keeps_small_content():
    payload = {"success": True, "items": [{"value": "x" * 10_000}]}
    raw = CallToolResult(
        content=[TextContent(type="text", text="Completed; full result is structured.")],
        structuredContent=payload,
    )

    sizes = measure_tool_result_sizes(raw)

    assert sizes["content_bytes"] < 100
    assert sizes["structured_bytes"] > 10_000


def test_measure_tool_result_sizes_counts_utf8_bytes():
    payload = {"message": "café"}
    raw = ([TextContent(type="text", text="café")], payload)

    sizes = measure_tool_result_sizes(raw)

    assert sizes["content_bytes"] == len("café".encode("utf-8"))
    assert sizes["structured_bytes"] == len(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def test_unwrap_result_accepts_direct_call_tool_result_structured_content():
    payload = {"success": True, "count": 2}
    raw = CallToolResult(
        content=[TextContent(type="text", text="Completed; full result is structured.")],
        structuredContent=payload,
    )

    assert LiveSmokeRunner.unwrap_result(object(), raw) == payload


def test_unwrap_result_accepts_direct_call_tool_result_text_fallback():
    payload = {"success": True, "count": 2}
    raw = CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload))],
    )

    assert LiveSmokeRunner.unwrap_result(object(), raw) == payload


@pytest.mark.asyncio
async def test_call_records_sizes_before_unwrapping(monkeypatch):
    events = []
    raw = ([TextContent(type="text", text='{"success":true}')], {"success": True})

    class FakeServer:
        async def call_tool(self, tool, args):
            events.append("call")
            return raw

    def measure(result):
        assert result is raw
        events.append("measure")
        return {"content_bytes": 16, "structured_bytes": 16, "combined_response_bytes": 32}

    runner = LiveSmokeRunner.__new__(LiveSmokeRunner)
    runner.server_key = "network"
    runner.server = FakeServer()
    runner.args = SimpleNamespace(delay=0)
    runner.report = SimpleNamespace(records=[])
    runner.cache = SimpleNamespace(remember=lambda tool, data: None)

    def unwrap(result):
        assert result is raw
        events.append("unwrap")
        return {"success": True}

    runner.unwrap_result = unwrap
    monkeypatch.setattr(_mod, "measure_tool_result_sizes", measure)

    record = await runner.call("unifi_test", {}, "readonly")

    assert events == ["call", "measure", "unwrap"]
    assert record.content_bytes == 16
    assert record.structured_bytes == 16
    assert record.combined_response_bytes == 32


def test_summarize_payload_preserves_only_safe_bounded_response_metadata():
    data = {
        "success": True,
        "summary_mode": True,
        "history_seconds": 3_600,
        "omitted_sections": ["radio_activity", "wan_activity", "wan_history", "wifi_activity"],
        "returned_count": 2,
        "total_count": 5,
        "limit": 2,
        "offset": 2,
        "next_offset": 4,
        "has_more": True,
        "rogue_aps": [{"ssid": "controller-value"}],
    }

    summary = summarize_payload(data)

    assert summary == {
        "success": True,
        "summary_mode": True,
        "history_seconds": 3_600,
        "omitted_sections": ["radio_activity", "wan_activity", "wan_history", "wifi_activity"],
        "returned_count": 2,
        "total_count": 5,
        "limit": 2,
        "offset": 2,
        "next_offset": 4,
        "has_more": True,
        "rogue_aps_count": 1,
    }
    assert "rogue_aps" not in summary
