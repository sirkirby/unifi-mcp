"""Incident evidence for Network and Protect: the bounded client view or the full document.

The payload is the whole view or document as JSON, not a field-by-field
mirror: the JSON Schema artifacts are the contract, and a Strawberry mirror
would be a second copy to drift. The contract denies secret-like keys by
construction, so no egress redaction applies.
"""

from __future__ import annotations

from typing import Any

import strawberry
from unifi_core.incident_evidence_view import EvidencePresentation, EvidenceViewTooLarge

from unifi_api.services.incident_evidence import IncidentRequestError


@strawberry.type(
    description=(
        "Bounded, read-only incident evidence: a unifi-incident-evidence-view (every source's coverage, "
        "failures and budget usage plus bounded record citations) or, with detail full, the whole "
        "unifi-incident-evidence document."
    )
)
class IncidentEvidence:
    document: strawberry.scalars.JSON = strawberry.field(  # type: ignore[name-defined]
        description=(
            "The unifi-incident-evidence-view, or the unifi-incident-evidence document with detail full. "
            "Check coverage_complete before treating an empty result as an all-clear."
        )
    )

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(
        cls, obj: Any, *, redact_sensitive: bool = True, presentation: EvidencePresentation | None = None
    ) -> "IncidentEvidence":
        """Raises ``IncidentRequestError`` when the evidence is too broad for its bounded view."""
        try:
            return cls(document=(presentation or EvidencePresentation()).render(obj))
        except EvidenceViewTooLarge as exc:
            raise IncidentRequestError(str(exc)) from None

    def to_dict(self) -> dict:
        return self.document
