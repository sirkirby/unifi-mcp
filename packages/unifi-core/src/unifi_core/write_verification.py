"""Structured verification for controller writes that may silently no-op.

UniFi's legacy endpoints can return ``rc: ok`` while dropping or coercing
individual fields.  This module classifies the post-write state without tying
the result to MCP, REST, or GraphQL response formatting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Collection, Mapping

_MISSING = object()


@dataclass(frozen=True)
class WriteVerificationResult:
    """Outcome of a controller mutation and its post-write read-back."""

    success: bool
    mutation_applied: bool
    operation: str
    resource: dict[str, Any] | None = None
    error: str | None = None
    persisted_fields: tuple[str, ...] = ()
    unchanged_fields: tuple[str, ...] = ()
    dropped_fields: tuple[str, ...] = ()
    coerced_fields: tuple[str, ...] = ()
    unverifiable_fields: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def partial_success(self) -> bool:
        """Whether the controller applied only part of the requested mutation."""
        return not self.success and bool(self.persisted_fields)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible, surface-neutral response envelope."""
        result: dict[str, Any] = {
            "success": self.success,
            "mutation_applied": self.mutation_applied,
            "partial_success": self.partial_success,
            "operation": self.operation,
            "persisted_fields": list(self.persisted_fields),
            "unchanged_fields": list(self.unchanged_fields),
            "dropped_fields": list(self.dropped_fields),
            "coerced_fields": list(self.coerced_fields),
            "unverifiable_fields": list(self.unverifiable_fields),
        }
        if self.resource is not None:
            result["details_after_attempt"] = self.resource
        if self.error:
            result["error"] = self.error
        result.update(self.metadata)
        return result


def _verification_error(operation: str, dropped: Collection[str], coerced: Collection[str]) -> str | None:
    parts: list[str] = []
    if dropped:
        parts.append(f"did not persist field(s): {', '.join(sorted(dropped))}")
    if coerced:
        parts.append(f"persisted different values for field(s): {', '.join(sorted(coerced))}")
    if not parts:
        return None
    return (
        f"Controller accepted and applied the {operation} request but "
        + "; ".join(parts)
        + ". The mutation was not rolled back; inspect details_after_attempt."
    )


def _numeric_string_equal(actual: Any, wanted: Any) -> bool:
    """Whether one side is the exact string form of the other's number.

    Controllers normalize numeric strings on persist (a requested vlan of
    ``"100"`` is echoed back as ``100``); that round-trip is persistence, not
    coercion. Booleans stay strict — ``True`` echoed as ``1`` is a real type
    change.
    """
    if isinstance(actual, str) and isinstance(wanted, (int, float)) and not isinstance(wanted, bool):
        return actual == str(wanted)
    if isinstance(wanted, str) and isinstance(actual, (int, float)) and not isinstance(actual, bool):
        return wanted == str(actual)
    return False


def _exact_equal(actual: Any, wanted: Any) -> bool:
    """Compare JSON-like values without Python's bool/int numeric coercion."""
    if type(actual) is not type(wanted):
        return _numeric_string_equal(actual, wanted)
    if isinstance(actual, dict):
        return actual.keys() == wanted.keys() and all(_exact_equal(actual[key], wanted[key]) for key in actual)
    if isinstance(actual, list):
        return len(actual) == len(wanted) and all(_exact_equal(left, right) for left, right in zip(actual, wanted))
    return bool(actual == wanted)


def verify_write(
    *,
    operation: str,
    requested: Mapping[str, Any],
    after: Mapping[str, Any],
    before: Mapping[str, Any] | None = None,
    unverifiable_fields: Collection[str] = (),
    absent_value_defaults: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> WriteVerificationResult:
    """Classify requested top-level fields against the post-write resource.

    Exact equality is required.  For updates, a mismatched value that remains
    equal to the pre-write value is classified as dropped; a different but still
    non-requested value is classified as coerced.  For creates, missing values
    are dropped and present-but-different values are coerced.

    ``absent_value_defaults`` maps field names to the value the controller
    means when it omits the key entirely (UniFi drops default-true ``enabled``
    flags on persist); an absent key then compares as that value instead of
    being classified as dropped.
    """
    unverifiable_set = set(unverifiable_fields)
    defaults = dict(absent_value_defaults or {})
    if defaults:
        after = {**{k: v for k, v in defaults.items() if k in requested}, **after}
        if before is not None:
            before = {**{k: v for k, v in defaults.items() if k in requested}, **before}
    persisted: list[str] = []
    unchanged: list[str] = []
    dropped: list[str] = []
    coerced: list[str] = []
    skipped: list[str] = []

    for key in sorted(requested):
        if key in unverifiable_set:
            skipped.append(key)
            continue

        wanted = requested[key]
        actual = after.get(key, _MISSING)
        if _exact_equal(actual, wanted):
            if before is not None and _exact_equal(before.get(key, _MISSING), wanted):
                unchanged.append(key)
            else:
                persisted.append(key)
            continue

        if actual is _MISSING:
            dropped.append(key)
            continue

        if before is not None and _exact_equal(actual, before.get(key, _MISSING)):
            dropped.append(key)
        else:
            coerced.append(key)

    error = _verification_error(operation, dropped, coerced)
    return WriteVerificationResult(
        success=error is None,
        mutation_applied=True,
        operation=operation,
        resource=dict(after),
        error=error,
        persisted_fields=tuple(persisted),
        unchanged_fields=tuple(unchanged),
        dropped_fields=tuple(dropped),
        coerced_fields=tuple(coerced),
        unverifiable_fields=tuple(skipped),
        metadata=dict(metadata or {}),
    )


def format_tool_payload(
    result: WriteVerificationResult,
    *,
    site: str,
    success_message: str,
) -> dict[str, Any]:
    """Format a verification result for the MCP tool response contract.

    One canonical envelope for every verified-write tool: adds ``site``, and on
    success renames ``details_after_attempt`` to ``details`` and attaches the
    success message. Callers add resource identifiers and failure ``error``
    text, which stay tool-specific.
    """
    payload = result.to_dict()
    payload["site"] = site
    if result.success:
        if "details_after_attempt" in payload:
            payload["details"] = payload.pop("details_after_attempt")
        payload["message"] = success_message
    return payload


def noop_write(
    *,
    operation: str = "update",
    resource: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> WriteVerificationResult:
    """Build a successful result for an update that required no controller call."""
    return WriteVerificationResult(
        success=True,
        mutation_applied=False,
        operation=operation,
        resource=dict(resource) if resource is not None else None,
        metadata=dict(metadata or {}),
    )


def failed_write(
    error: str,
    *,
    operation: str = "write",
    mutation_applied: bool = False,
    resource: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> WriteVerificationResult:
    """Build a failed result when exact field classification is unavailable."""
    return WriteVerificationResult(
        success=False,
        mutation_applied=mutation_applied,
        operation=operation,
        resource=dict(resource) if resource is not None else None,
        error=error,
        metadata=dict(metadata or {}),
    )
