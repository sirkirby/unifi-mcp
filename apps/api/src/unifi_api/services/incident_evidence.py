"""Bounded, read-only incident evidence collection shared by REST and GraphQL.

Request validation lives in the Core request models; this module turns raw
transport arguments into those models, then runs the Core collectors with a
way to acquire the event manager rather than the manager itself. The
collector acquires it inside its first read, so invalid input and a window
longer than its budget never touch the controller, acquisition counts
against the elapsed budget, and an acquisition failure becomes a classified
source failure in the document instead of an error.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError
from unifi_core.incident_collection import describe_validation_error
from unifi_core.incident_evidence import IncidentEvidence
from unifi_core.network.incident_collection import collect_network_incident_evidence
from unifi_core.network.models.incident_evidence import NetworkIncidentRequest
from unifi_core.protect.incident_collection import collect_protect_incident_evidence
from unifi_core.protect.models.incident_evidence import ProtectIncidentRequest

__all__ = [
    "ControllerCapabilityError",
    "IncidentRequestError",
    "collect_network_evidence",
    "collect_protect_evidence",
    "network_request",
    "protect_request",
    "require_product",
]

Acquire = Callable[[], Awaitable[Any]]


class IncidentRequestError(ValueError):
    """The incident request is malformed; the message never echoes the rejected input."""


class ControllerCapabilityError(ValueError):
    """The controller does not run the product; REST answers 409 capability_mismatch."""

    def __init__(self, product: str) -> None:
        super().__init__(f"controller does not support {product}")
        self.product = product


def require_product(controller: Any, product: str) -> None:
    """Raise ``ControllerCapabilityError`` unless ``controller`` runs ``product`` (no controller I/O)."""
    if product not in [kind for kind in controller.product_kinds.split(",") if kind]:
        raise ControllerCapabilityError(product)


def _parse_mappings(mappings: Any) -> Any:
    """Accept the mappings as a JSON-encoded string (query parameters) or an already decoded list."""
    if mappings is None or not isinstance(mappings, str):
        return mappings
    try:
        return json.loads(mappings)
    except ValueError:
        raise IncidentRequestError("mappings: must be a JSON-encoded array of mapping assertions") from None


def _build_request(model: type, arguments: dict[str, Any]) -> Any:
    # Omitted budgets take the Core defaults, so every adapter shares them.
    values = {key: value for key, value in arguments.items() if value is not None}
    values["mappings"] = _parse_mappings(values.get("mappings"))
    try:
        return model(**values)
    except ValidationError as exc:
        raise IncidentRequestError(describe_validation_error(exc, model)) from None


def network_request(**arguments: Any) -> NetworkIncidentRequest:
    """Validate Network incident arguments; raises ``IncidentRequestError``."""
    return _build_request(NetworkIncidentRequest, arguments)


def protect_request(**arguments: Any) -> ProtectIncidentRequest:
    """Validate Protect incident arguments; raises ``IncidentRequestError``."""
    return _build_request(ProtectIncidentRequest, arguments)


async def collect_network_evidence(acquire: Acquire, request: NetworkIncidentRequest, *, site: str) -> IncidentEvidence:
    """Collect Network incident evidence, acquiring the event manager only inside the first read."""
    return await collect_network_incident_evidence(acquire, request, site=site)


async def collect_protect_evidence(acquire: Acquire, request: ProtectIncidentRequest) -> IncidentEvidence:
    """Collect Protect incident evidence, acquiring the event manager only inside the first read."""
    return await collect_protect_incident_evidence(acquire, request)
