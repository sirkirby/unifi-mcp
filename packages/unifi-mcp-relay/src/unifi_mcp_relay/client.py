"""WebSocket client that connects to the Cloudflare Worker relay."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import websockets

from unifi_mcp_relay.config import RelayConfig
from unifi_mcp_relay.protocol import (
    CatalogUpdateMessage,
    ErrorMessage,
    HeartbeatAckMessage,
    HeartbeatMessage,
    RegisteredMessage,
    RegisterMessage,
    ToolCallMessage,
    ToolInfo,
    ToolResultMessage,
    parse_message,
)

logger = logging.getLogger("unifi-mcp-relay")

# Handler type: takes (tool_name, arguments), returns (result, None) or (None, error_string)
ToolCallHandler = Callable[[str, dict], Awaitable[tuple[dict | None, str | None]]]

# Auth-related close codes that should stop reconnection
_AUTH_FAILURE_CODES = {4001, 4003}


class RelayClient:
    """WebSocket client that connects to the relay worker, registers tools,
    handles heartbeats, forwards tool calls, and reconnects on failure."""

    def __init__(self, config: RelayConfig) -> None:
        self._config = config
        self._ws_url = self._build_ws_url(config.relay_url)
        self._ws: object | None = None
        self._location_id: str | None = None
        self._tool_call_handler: ToolCallHandler | None = None
        self._running: bool = False

    @staticmethod
    def _build_ws_url(relay_url: str) -> str:
        """Convert relay HTTP URL to WebSocket URL with /ws path."""
        url = relay_url.rstrip("/")
        if url.startswith("https://"):
            url = "wss://" + url[len("https://"):]
        elif url.startswith("http://"):
            url = "ws://" + url[len("http://"):]
        return url + "/ws"

    async def _connect_and_register(self, tools: list[ToolInfo]) -> None:
        """Connect to the relay WebSocket and send registration message.

        Sets self._ws and self._location_id on success.
        Raises ConnectionError if registration fails.
        """
        subprotocols = [
            websockets.Subprotocol(self._config.relay_token),
            websockets.Subprotocol("unifi-relay-v1"),
        ]

        ws = await websockets.connect(
            self._ws_url,
            subprotocols=subprotocols,
            additional_headers={"User-Agent": "unifi-mcp-relay/1.0"},
        )

        # Send registration
        register_msg = RegisterMessage(
            token=self._config.relay_token,
            location_name=self._config.location_name,
            tools=tools,
        )
        await ws.send(register_msg.to_json())

        # Wait for registration confirmation
        raw = await ws.recv()
        response = parse_message(raw)

        if not isinstance(response, RegisteredMessage):
            await ws.close()
            raise ConnectionError(
                f"Registration failed: expected RegisteredMessage, got {type(response).__name__}"
            )

        self._ws = ws
        self._location_id = response.location_id
        logger.info(
            "[client] Registered at relay as location '%s' (id=%s)",
            response.location_name,
            response.location_id,
        )

    async def _handle_message(self, msg: object | None, ws: object) -> None:
        """Dispatch an inbound message to the appropriate handler."""
        if msg is None:
            return

        if isinstance(msg, HeartbeatMessage):
            ack = HeartbeatAckMessage()
            await ws.send(ack.to_json())
        elif isinstance(msg, ToolCallMessage):
            # Spawn as a task so multiple calls run concurrently
            asyncio.create_task(self._handle_tool_call(msg, ws))
        elif isinstance(msg, ErrorMessage):
            logger.warning("[client] Error from relay: %s (code=%s)", msg.message, msg.code)
        else:
            logger.debug("[client] Unhandled message type: %s", type(msg).__name__)

    async def _handle_tool_call(self, msg: ToolCallMessage, ws: object) -> None:
        """Handle a single tool call, invoking the handler and sending the result."""
        if self._tool_call_handler is None:
            error_result = ToolResultMessage(call_id=msg.call_id, error="No tool call handler configured")
            await ws.send(error_result.to_json())
            return

        try:
            result, error = await self._tool_call_handler(msg.tool_name, msg.arguments)
            if error is not None:
                response = ToolResultMessage(call_id=msg.call_id, error=error)
            else:
                response = ToolResultMessage(call_id=msg.call_id, result=result)
        except Exception as exc:
            logger.error("[client] Tool call handler raised for '%s': %s", msg.tool_name, exc, exc_info=True)
            response = ToolResultMessage(call_id=msg.call_id, error=str(exc))

        try:
            await ws.send(response.to_json())
        except Exception as exc:
            logger.error("[client] Failed to send tool result for call_id=%s: %s", msg.call_id, exc)

    async def _message_loop(self, ws: object) -> None:
        """Read and dispatch messages until the connection closes."""
        async for raw in ws:
            msg = parse_message(raw)
            await self._handle_message(msg, ws)

    async def run(
        self,
        tools: list[ToolInfo],
        tool_call_handler: ToolCallHandler,
    ) -> None:
        """Main loop: connect, register, handle messages, reconnect on failure.

        Reconnects with exponential backoff. Stops on auth failures (close codes 4001/4003
        or 'rejected'/'auth' in error messages).
        """
        self._tool_call_handler = tool_call_handler
        self._running = True
        backoff = 1.0

        while self._running:
            try:
                await self._connect_and_register(tools)
                backoff = 1.0  # Reset on successful connection
                logger.info("[client] Connected and registered, entering message loop")
                await self._message_loop(self._ws)
            except websockets.ConnectionClosed as exc:
                if self._is_auth_failure(exc):
                    logger.error(
                        "[client] Authentication failure (code=%s, reason=%s). Stopping.",
                        exc.code,
                        exc.reason,
                    )
                    self._running = False
                    break
                logger.warning(
                    "[client] Connection closed (code=%s, reason=%s). Reconnecting in %.1fs...",
                    exc.code,
                    exc.reason,
                    backoff,
                )
            except ConnectionError as exc:
                error_str = str(exc).lower()
                if "rejected" in error_str or "auth" in error_str:
                    logger.error("[client] Auth-related connection error: %s. Stopping.", exc)
                    self._running = False
                    break
                logger.warning("[client] Connection error: %s. Reconnecting in %.1fs...", exc, backoff)
            except Exception as exc:
                logger.error("[client] Unexpected error: %s. Reconnecting in %.1fs...", exc, backoff, exc_info=True)

            if self._running:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._config.reconnect_max_delay)

        self._ws = None
        logger.info("[client] Run loop ended")

    @staticmethod
    def _is_auth_failure(exc: websockets.ConnectionClosed) -> bool:
        """Check if a connection close indicates an authentication failure."""
        if exc.code in _AUTH_FAILURE_CODES:
            return True
        reason = (exc.reason or "").lower()
        if "rejected" in reason or "auth" in reason:
            return True
        return False

    async def send_catalog_update(self, tools: list[ToolInfo]) -> bool:
        """Send a catalog update over the active WebSocket.

        Returns True if sent successfully, False if not connected.
        """
        if self._ws is None or not getattr(self._ws, "open", False):
            return False

        msg = CatalogUpdateMessage(tools=tools)
        await self._ws.send(msg.to_json())
        logger.info("[client] Sent catalog update with %d tools", len(tools))
        return True

    async def stop(self) -> None:
        """Graceful shutdown: stop the run loop and close the WebSocket."""
        self._running = False
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception as exc:
                logger.debug("[client] Error closing WebSocket: %s", exc)
            self._ws = None
