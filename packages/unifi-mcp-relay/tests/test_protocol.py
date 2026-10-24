import json
from pathlib import Path

import pytest
from unifi_mcp_relay.protocol import (
    RegisterMessage,
    ToolInfo,
    parse_message,
)

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures"


def test_register_message_matches_worker_contract_fixture():
    tool = ToolInfo(
        name="list_devices",
        title="List Devices",
        description="List devices",
        input_schema={"type": "object", "properties": {"site": {"type": "string"}}},
        annotations={"readOnlyHint": True, "openWorldHint": False},
        server_origin="unifi-network-mcp",
    )
    msg = RegisterMessage(token="test-token", location_name="Home Lab", tools=[tool], capabilities=["fan_out_v1"])

    fixture = json.loads((FIXTURES_DIR / "relay_register_with_metadata.json").read_text())

    assert json.loads(msg.to_json()) == fixture


@pytest.mark.parametrize(
    "raw",
    [
        json.dumps({"type": "unknown_thing", "data": 123}),
        "this is not json {{{",
        json.dumps({"type": "registered", "location_name": "Test"}),
        json.dumps({"type": "tool_call", "tool_name": "some_tool", "arguments": {}}),
        json.dumps({"type": "tool_call", "call_id": "123", "arguments": {}}),
    ],
)
def test_parse_invalid_or_unknown_message_returns_none(raw):
    assert parse_message(raw) is None
