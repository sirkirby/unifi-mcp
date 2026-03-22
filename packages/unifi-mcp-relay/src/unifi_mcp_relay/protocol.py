"""WebSocket protocol message types for relay communication."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field

logger = logging.getLogger("unifi-mcp-relay")

PROTOCOL_VERSION = 1


@dataclass
class ToolInfo:
    """Tool metadata sent during registration."""

    name: str
    description: str
    input_schema: dict | None = None
    annotations: dict | None = None
    server_origin: str | None = None


# --- Outbound messages (relay -> worker) ---


@dataclass
class RegisterMessage:
    """Sent on connect to authenticate and register tools."""

    token: str
    location_name: str
    tools: list[ToolInfo] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=lambda: ["fan_out_v1"])

    def to_json(self) -> str:
        data = {
            "type": "register",
            "protocol_version": PROTOCOL_VERSION,
            "token": self.token,
            "location_name": self.location_name,
            "tools": [asdict(t) for t in self.tools],
            "capabilities": self.capabilities,
        }
        return json.dumps(data)


@dataclass
class ToolResultMessage:
    """Response to a tool_call from the worker."""

    call_id: str
    result: dict | None = None
    error: str | None = None

    def to_json(self) -> str:
        data: dict = {"type": "tool_result", "call_id": self.call_id}
        if self.error is not None:
            data["error"] = self.error
        else:
            data["result"] = self.result
        return json.dumps(data)


@dataclass
class CatalogUpdateMessage:
    """Sent when periodic refresh detects tool catalog changes."""

    tools: list[ToolInfo] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=lambda: ["fan_out_v1"])

    def to_json(self) -> str:
        data = {
            "type": "catalog_update",
            "tools": [asdict(t) for t in self.tools],
            "capabilities": self.capabilities,
        }
        return json.dumps(data)


@dataclass
class HeartbeatAckMessage:
    """Pong response to worker heartbeat."""

    def to_json(self) -> str:
        return json.dumps({"type": "heartbeat_ack"})


# --- Inbound messages (worker -> relay) ---


@dataclass
class RegisteredMessage:
    """Confirmation of successful registration."""

    location_id: str
    location_name: str


@dataclass
class ToolCallMessage:
    """Tool invocation forwarded from cloud agent via worker."""

    call_id: str
    tool_name: str
    arguments: dict = field(default_factory=dict)
    timeout_ms: int = 30000


@dataclass
class HeartbeatMessage:
    """Ping from worker."""

    pass


@dataclass
class ErrorMessage:
    """Error notification from worker."""

    message: str
    code: str | None = None


def parse_message(
    raw: str,
) -> RegisteredMessage | ToolCallMessage | HeartbeatMessage | ErrorMessage | None:
    """Parse an inbound WebSocket message from the worker."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("[protocol] Failed to parse message: %s", raw[:200])
        return None

    msg_type = data.get("type")
    if msg_type == "registered":
        return RegisteredMessage(location_id=data["location_id"], location_name=data["location_name"])
    elif msg_type == "tool_call":
        return ToolCallMessage(
            call_id=data["call_id"],
            tool_name=data["tool_name"],
            arguments=data.get("arguments", {}),
            timeout_ms=data.get("timeout_ms", 30000),
        )
    elif msg_type == "heartbeat":
        return HeartbeatMessage()
    elif msg_type == "error":
        return ErrorMessage(message=data.get("message", "Unknown error"), code=data.get("code"))
    else:
        logger.debug("[protocol] Unknown message type: %s", msg_type)
        return None
