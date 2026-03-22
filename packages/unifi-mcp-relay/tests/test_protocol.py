import json
from unifi_mcp_relay.protocol import (
    RegisterMessage, RegisteredMessage, ToolCallMessage, ToolResultMessage,
    CatalogUpdateMessage, HeartbeatAckMessage, ToolInfo, parse_message, PROTOCOL_VERSION,
)

def test_register_message_serialization():
    tool = ToolInfo(name="list_devices", description="List devices", input_schema={"type": "object"}, annotations={"readOnlyHint": True}, server_origin="unifi-network-mcp")
    msg = RegisterMessage(token="test-token", location_name="Home Lab", tools=[tool], capabilities=["fan_out_v1"])
    data = json.loads(msg.to_json())
    assert data["type"] == "register"
    assert data["protocol_version"] == PROTOCOL_VERSION
    assert data["location_name"] == "Home Lab"
    assert len(data["tools"]) == 1
    assert data["tools"][0]["name"] == "list_devices"

def test_parse_registered_message():
    raw = json.dumps({"type": "registered", "location_id": "loc_abc123", "location_name": "Home Lab"})
    msg = parse_message(raw)
    assert isinstance(msg, RegisteredMessage)
    assert msg.location_id == "loc_abc123"

def test_parse_tool_call_message():
    raw = json.dumps({"type": "tool_call", "call_id": "uuid-123", "tool_name": "list_devices", "arguments": {"compact": True}, "timeout_ms": 30000})
    msg = parse_message(raw)
    assert isinstance(msg, ToolCallMessage)
    assert msg.call_id == "uuid-123"
    assert msg.tool_name == "list_devices"
    assert msg.arguments == {"compact": True}

def test_tool_result_success_serialization():
    msg = ToolResultMessage(call_id="uuid-123", result={"success": True, "data": [1, 2, 3]})
    data = json.loads(msg.to_json())
    assert data["type"] == "tool_result"
    assert data["call_id"] == "uuid-123"
    assert data["result"]["success"] is True
    assert "error" not in data

def test_tool_result_transport_error_serialization():
    msg = ToolResultMessage(call_id="uuid-123", error="Connection refused")
    data = json.loads(msg.to_json())
    assert data["type"] == "tool_result"
    assert data["error"] == "Connection refused"
    assert "result" not in data

def test_heartbeat_ack_serialization():
    msg = HeartbeatAckMessage()
    data = json.loads(msg.to_json())
    assert data["type"] == "heartbeat_ack"

def test_parse_unknown_message_type():
    raw = json.dumps({"type": "unknown_thing", "data": 123})
    msg = parse_message(raw)
    assert msg is None
