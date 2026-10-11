"""Versioned unifi-incident-evidence document for Network and Protect.

The payload is the whole document as JSON, not a field-by-field mirror: the
JSON Schema artifact for the document is the contract, and a Strawberry mirror
would be a second copy to drift. The contract denies secret-like keys by
construction, so no egress redaction applies.
"""

from __future__ import annotations

from typing import Any

import strawberry
from unifi_core.incident_evidence import evidence_to_json


@strawberry.type(
    description=(
        "Bounded, read-only incident evidence: a versioned unifi-incident-evidence document with cited "
        "records plus per-source coverage, failures and budget usage."
    )
)
class IncidentEvidence:
    document: strawberry.scalars.JSON = strawberry.field(  # type: ignore[name-defined]
        description=(
            "The unifi-incident-evidence document. Check coverage_complete before treating an empty "
            "result as an all-clear."
        )
    )

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: Any, *, redact_sensitive: bool = True) -> "IncidentEvidence":
        return cls(document=evidence_to_json(obj))

    def to_dict(self) -> dict:
        return self.document
