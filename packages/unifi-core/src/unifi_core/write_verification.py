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


def verify_write(
    *,
    operation: str,
    requested: Mapping[str, Any],
    after: Mapping[str, Any],
    before: Mapping[str, Any] | None = None,
    unverifiable_fields: Collection[str] = (),
    metadata: Mapping[str, Any] | None = None,
) -> WriteVerificationResult:
    """Classify requested top-level fields against the post-write resource.

    Exact equality is required.  For updates, a mismatched value that remains
    equal to the pre-write value is classified as dropped; a different but still
    non-requested value is classified as coerced.  For creates, missing values
    are dropped and present-but-different values are coerced.
    """
    unverifiable_set = set(unverifiable_fields)
    persisted: list[str] = []
    dropped: list[str] = []
    coerced: list[str] = []
    skipped: list[str] = []

    for key in sorted(requested):
        if key in unverifiable_set:
            skipped.append(key)
            continue

        wanted = requested[key]
        actual = after.get(key, _MISSING)
        if actual == wanted:
            persisted.append(key)
            continue

        if actual is _MISSING:
            dropped.append(key)
            continue

        if before is not None and actual == before.get(key, _MISSING):
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
        dropped_fields=tuple(dropped),
        coerced_fields=tuple(coerced),
        unverifiable_fields=tuple(skipped),
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
