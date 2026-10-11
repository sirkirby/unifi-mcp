"""An EventManager on a real ConnectionManager whose transport is the SDK's own decoder.

Only the HTTP exchange is replaced: each request is answered by
``api_request.decode(<body as JSON bytes>)``, so ``ApiRequestV2`` wrapping,
legacy ``meta.rc`` error raising and ``ConnectionManager.request`` unwrapping
all run exactly as they do against a controller.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.managers.event_manager import EventManager


def sdk_event_manager(*bodies: Any, v2: bool = True) -> EventManager:
    """Answer successive requests with ``bodies`` (the last one repeats); an exception body is raised."""
    connection = ConnectionManager("controller.invalid", "fixture-user", "fixture-password")
    connection.ensure_connected = AsyncMock(return_value=True)
    connection.controller = MagicMock()
    sent: list[Any] = []
    remaining = list(bodies)

    async def transport(api_request: Any) -> Any:
        sent.append(api_request)
        body = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        if isinstance(body, BaseException):
            raise body
        return api_request.decode(json.dumps(body).encode())

    connection.controller.request = transport
    manager = EventManager(connection)
    manager._use_v2 = v2
    manager.sent_requests = sent  # type: ignore[attr-defined]
    return manager
