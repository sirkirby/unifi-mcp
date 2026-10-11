"""Bounded, read-only incident evidence collection shared by REST and GraphQL.

Request validation lives in the Core request models; this module only turns raw
transport arguments into those models and runs the Core collectors. Failures of
an individual evidence source live inside the returned document, so the only
errors raised here are malformed requests.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError
from unifi_core.incident_collection import (
    DEFAULT_CALLS,
    DEFAULT_ELAPSED_MS,
    DEFAULT_EVENTS,
    DEFAULT_WINDOW_SECONDS,
    describe_validation_error,
)
from unifi_core.network.incident_collection import collect_network_incident_evidence
from unifi_core.network.models.incident_evidence import NetworkIncidentRequest
from unifi_core.protect.incident_collection import collect_protect_incident_evidence
from unifi_core.protect.models.incident_evidence import ProtectIncidentRequest

__all__ = [
    "DEFAULT_CALLS",
    "DEFAULT_ELAPSED_MS",
    "DEFAULT_EVENTS",
    "DEFAULT_WINDOW_SECONDS",
    "IncidentRequestError",
    "collect_network_evidence",
    "collect_protect_evidence",
]


class IncidentRequestError(ValueError):
    """The incident request is malformed; the message never echoes the rejected input."""


def _parse_mappings(mappings: Any) -> Any:
    """Accept the mappings as a JSON-encoded string (query parameters) or an already decoded list."""
    if mappings is None or not isinstance(mappings, str):
        return mappings
    try:
        return json.loads(mappings)
    except ValueError:
        raise IncidentRequestError("mappings: must be a JSON-encoded array of mapping assertions") from None


def _build_request(model: type, **arguments: Any) -> Any:
    arguments["mappings"] = _parse_mappings(arguments.get("mappings"))
    try:
        return model(**arguments)
    except ValidationError as exc:
        raise IncidentRequestError(describe_validation_error(exc)) from None


async def collect_network_evidence(
    events: Any,
    *,
    site: str,
    start: str,
    end: str,
    device_macs: list[str] | None = None,
    location_id: str | None = None,
    max_window_seconds: int = DEFAULT_WINDOW_SECONDS,
    max_events: int = DEFAULT_EVENTS,
    max_calls: int = DEFAULT_CALLS,
    max_elapsed_ms: int = DEFAULT_ELAPSED_MS,
    mappings: Any = None,
) -> Any:
    """Collect Network incident evidence; returns the Core evidence object."""
    request = _build_request(
        NetworkIncidentRequest,
        start=start,
        end=end,
        device_macs=device_macs,
        location_id=location_id,
        max_window_seconds=max_window_seconds,
        max_events=max_events,
        max_calls=max_calls,
        max_elapsed_ms=max_elapsed_ms,
        mappings=mappings,
    )
    return await collect_network_incident_evidence(events, request, site=site)


async def collect_protect_evidence(
    events: Any,
    *,
    start: str,
    end: str,
    camera_ids: list[str] | None = None,
    location_id: str | None = None,
    max_window_seconds: int = DEFAULT_WINDOW_SECONDS,
    max_events: int = DEFAULT_EVENTS,
    max_calls: int = DEFAULT_CALLS,
    max_elapsed_ms: int = DEFAULT_ELAPSED_MS,
    mappings: Any = None,
) -> Any:
    """Collect Protect incident evidence; returns the Core evidence object."""
    request = _build_request(
        ProtectIncidentRequest,
        start=start,
        end=end,
        camera_ids=camera_ids,
        location_id=location_id,
        max_window_seconds=max_window_seconds,
        max_events=max_events,
        max_calls=max_calls,
        max_elapsed_ms=max_elapsed_ms,
        mappings=mappings,
    )
    return await collect_protect_incident_evidence(events, request)
