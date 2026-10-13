"""A Protect EventManager on a real uiprotect client whose HTTP exchange is replaced.

``ProtectApiClient.api_request_raw`` answers with the bytes given, so the
SDK's own JSON decoding and error raising run exactly as they do against an
NVR. Every request's method, URL and parameters are recorded.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from uiprotect.api import ProtectApiClient
from unifi_core.protect.managers.event_manager import EventManager


def sdk_protect_event_manager(*bodies: Any) -> EventManager:
    """Answer successive requests with ``bodies`` (the last one repeats).

    A ``bytes`` body is sent as-is, an exception is raised, anything else is
    JSON-encoded.
    """
    client = ProtectApiClient("controller.invalid", 443, "fixture-user", "fixture-password", store_sessions=False)
    sent: list[dict[str, Any]] = []
    remaining = list(bodies)

    async def api_request_raw(url: str, method: str = "get", **kwargs: Any) -> bytes:
        sent.append({"url": url, "method": method, **kwargs})
        body = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        if isinstance(body, BaseException):
            raise body
        return body if isinstance(body, bytes) else json.dumps(body).encode()

    client.api_request_raw = api_request_raw  # type: ignore[method-assign]
    manager = EventManager(SimpleNamespace(client=client), {})
    manager.sent_requests = sent  # type: ignore[attr-defined]
    return manager
