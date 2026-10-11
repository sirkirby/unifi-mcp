"""Transport-only consumer of Core's incident evidence contract."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError
from unifi_core.incident_collection import combine_incident_evidence, describe_validation_error
from unifi_core.incident_evidence import (
    BudgetKind,
    Budgets,
    BudgetUsage,
    FailureKind,
    IncidentEvidence,
    Product,
    Scope,
    SourceContext,
    SourceFailure,
    assemble_incident_evidence,
    evidence_to_json,
    failure_from_exception,
    format_utc,
    source_failed,
    validate_incident_evidence,
)
from unifi_core.network.models.incident_evidence import NetworkIncidentRequest
from unifi_core.protect.models.incident_evidence import ProtectIncidentRequest

logger = logging.getLogger("unifi-mcp-relay")

TOOL_NAME = "unifi_location_timeline"
TOOL_DESCRIPTION = (
    "Collect bounded, read-only Network and Protect incident evidence for one window. "
    "Returns a versioned evidence document with per-source coverage, failures and budgets. "
    "Use exact device MACs, camera IDs and explicit mappings; names never establish mappings. "
    "Access, when requested, is explicitly unsupported. Inspect overall and coverage_complete."
)

# Reuse Core's argument models, including the closed mapping assertion schema.
_network_schema = NetworkIncidentRequest.model_json_schema()
_protect_schema = ProtectIncidentRequest.model_json_schema()
TOOL_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "$defs": {**_network_schema["$defs"], **_protect_schema["$defs"]},
    "properties": {
        **_network_schema["properties"],
        "camera_ids": _protect_schema["properties"]["camera_ids"],
        "products": {
            "type": "array",
            "items": {"type": "string", "enum": ["network", "protect", "access"]},
            "minItems": 1,
            "uniqueItems": True,
            "default": ["network", "protect"],
            "description": "Products to collect. Access is reported unsupported.",
        },
    },
    "required": ["start", "end"],
}
TOOL_ANNOTATIONS = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
PRODUCT_TOOLS = {"network": "unifi_get_incident_evidence", "protect": "protect_get_incident_evidence"}


def _failure_document(request: NetworkIncidentRequest | ProtectIncidentRequest, product: str, failure: SourceFailure):
    """An unanswered product call makes no window or pagination claim."""
    context = SourceContext(
        source_id=f"{product}.incident_evidence",
        product=Product(product),
        api_family=None,
        source_tool=PRODUCT_TOOLS.get(product),
        scope=Scope(location_id=request.location_id),
        query={"start": request.start, "end": request.end},
        collected_at=format_utc(datetime.now(timezone.utc)),
        requested_window=request.window,
    )
    return assemble_incident_evidence(
        requested_window=request.window,
        budgets=Budgets(
            limits=request.limits,
            usage=BudgetUsage(),
            exhausted=(BudgetKind.WINDOW,) if request.window_exhausted else (),
        ),
        mappings=request.mappings,
        sources=[source_failed(context, failure)],
    )


def _validate_product_document(value: Any, request: Any, product: str) -> IncidentEvidence:
    document = validate_incident_evidence(value)
    if (
        document.requested_window != request.window
        or document.budgets.limits != request.limits
        or document.mappings != request.mappings
        or any(source.product.value != product for source in document.sources)
        or (
            request.location_id is not None
            and any(source.scope.location_id != request.location_id for source in document.sources)
        )
    ):
        raise ValueError("product evidence does not describe the requested collection")
    return document


async def handle_location_timeline(
    arguments: dict[str, Any],
    forwarder: Any,
    location_id: str | None = None,
    location_name: str | None = None,
    is_relay_mode: bool = True,
) -> dict[str, Any]:
    """Forward real product requests, validate their documents and combine in Core.

    Error envelopes have no structured failure category, so they are unavailable;
    raw error text is neither copied nor used to guess a category. Exceptions are
    classified by Core. Display names are intentionally not evidence inputs.
    """
    try:
        if not isinstance(arguments, dict) or set(arguments) - TOOL_INPUT_SCHEMA["properties"].keys():
            raise ValueError("unsupported arguments; use start/end and exact identifiers")
        products = arguments.get("products", ["network", "protect"])
        if (
            not isinstance(products, list)
            or not products
            or any(not isinstance(product, str) or product not in (*PRODUCT_TOOLS, "access") for product in products)
            or len(products) != len(set(products))
        ):
            raise ValueError("products must be a nonempty unique list of network, protect or access")
        if not is_relay_mode and arguments.get("location_id") is not None:
            raise ValueError("location_id requires relay mode")
        common = {
            key: value for key, value in arguments.items() if key not in ("products", "device_macs", "camera_ids")
        }
        if location_id is not None:
            if common.get("location_id") not in (None, location_id):
                raise ValueError("location_id must match the relay location")
            common["location_id"] = location_id
        network = NetworkIncidentRequest(**common, device_macs=arguments.get("device_macs"))
        protect = ProtectIncidentRequest(**common, camera_ids=arguments.get("camera_ids"))
    except ValidationError as exc:
        return {"success": False, "error": f"Failed to collect location evidence: {describe_validation_error(exc)}"}
    except ValueError as exc:
        return {"success": False, "error": f"Failed to collect location evidence: {exc}"}

    async def collect(product: str) -> IncidentEvidence:
        request = protect if product == "protect" else network
        tool_name = PRODUCT_TOOLS.get(product)
        if tool_name is None:
            return _failure_document(request, product, SourceFailure(kind=FailureKind.UNSUPPORTED))
        try:
            async with asyncio.timeout(request.max_elapsed_ms / 1000):
                response = await forwarder.forward(tool_name=tool_name, arguments=request.model_dump(mode="json"))
        except Exception as exc:
            logger.warning("Incident evidence transport failed for %s: %s", product, type(exc).__name__)
            return _failure_document(request, product, failure_from_exception(exc))
        if response is None:
            return _failure_document(request, product, SourceFailure(kind=FailureKind.UNSUPPORTED))
        if isinstance(response, dict) and response.get("success") is False:
            return _failure_document(request, product, SourceFailure(kind=FailureKind.UNAVAILABLE))
        try:
            if not isinstance(response, dict) or response.get("success") is not True:
                raise ValueError("invalid evidence envelope")
            return _validate_product_document(response.get("data"), request, product)
        except Exception:
            return _failure_document(request, product, SourceFailure(kind=FailureKind.PARSE_FAILED))

    try:
        documents = await asyncio.gather(*(collect(product) for product in products))
        return {"success": True, "data": evidence_to_json(combine_incident_evidence(documents))}
    except Exception as exc:
        logger.error("Combining location incident evidence failed: %s", type(exc).__name__)
        return {
            "success": False,
            "error": "Failed to combine location incident evidence: conflicting or invalid evidence",
        }
