"""Generate transport-consumer combine fixtures using the Python reference.

Run with ``uv run --package unifi-core python
 tests/fixtures/incident_evidence/generate_combine.py [--check]``.
The check mode is also exercised by the relay suite.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from unifi_core.incident_collection import combine_incident_evidence
from unifi_core.incident_evidence import (
    BudgetKind,
    Budgets,
    BudgetUsage,
    ExtractedRecord,
    FailureKind,
    SourceContext,
    SourceEvidence,
    SourceFailure,
    assemble_incident_evidence,
    collect_source,
    evidence_to_json,
    source_failed,
    validate_incident_evidence,
)

ROOT = Path(__file__).resolve().parent


def load(name):
    return validate_incident_evidence(json.loads((ROOT / "cases" / f"{name}.json").read_text())["expected"])


def split(document, product, *, mappings=None, use_document_mappings=True):
    return assemble_incident_evidence(
        requested_window=document.requested_window,
        budgets=document.budgets,
        mappings=document.mappings if use_document_mappings else mappings,
        sources=[
            SourceEvidence(source=source, records=tuple(r for r in document.records if r.source_id == source.source_id))
            for source in document.sources
            if source.product.value == product
        ],
    )


def failure(reference, kind):
    context = SourceContext(
        source_id=f"fixture.failure.{kind}",
        product="network",
        api_family=None,
        source_tool="unifi_get_incident_evidence",
        collected_at="2026-08-08T13:05:00.000000Z",
        requested_window=reference.requested_window,
    )
    return assemble_incident_evidence(
        requested_window=reference.requested_window,
        budgets=Budgets(limits=reference.budgets.limits, usage=BudgetUsage()),
        sources=[source_failed(context, SourceFailure(kind=FailureKind(kind)))],
    )


def edge_document(reference):
    context = SourceContext(
        source_id="fixture.encoding",
        product="network",
        api_family=None,
        source_tool="unifi_get_incident_evidence",
        collected_at="2026-08-08T13:05:00.000000Z",
        requested_window=reference.requested_window,
        queried_window=reference.requested_window,
        has_more=False,
        offset=0,
    )
    rows = [
        {"id": "fixture-!'()*/é", "time": "1786191000.000"},
        {"id": "fixture-negative-zero", "time": "2026-08-08T12:12:00-00:00"},
        {"id": "fixture-precise", "time": "1786191000.1234565"},
        {"id": None, "time": "2026-08-08T12:15:00Z"},
    ]

    def extract(raw):
        return ExtractedRecord(
            record_id=raw["id"],
            record_id_field="id" if raw["id"] is not None else None,
            time_field="time",
            time_value=raw["time"],
            event_type="fixture-event",
            summary="fixture café 😀",
            attributes={"fraction": 0.125},
        )

    return assemble_incident_evidence(
        requested_window=reference.requested_window,
        budgets=reference.budgets,
        sources=[collect_source(context, rows, extract)],
    )


def fixtures():
    full = load("network_protect_real_shapes")
    network, protect = split(full, "network"), split(full, "protect")
    spent = assemble_incident_evidence(
        requested_window=network.requested_window,
        budgets=Budgets(
            limits=network.budgets.limits,
            usage=network.budgets.usage,
            exhausted=(BudgetKind.EVENTS,),
        ),
        sources=[
            SourceEvidence(source=s, records=tuple(r for r in network.records if r.source_id == s.source_id))
            for s in network.sources
        ],
    )
    conflicting = failure(network, "timeout")
    changed = conflicting.model_dump(mode="json", by_alias=True)
    changed["sources"][0]["collected_at"] = "2026-08-08T13:06:00.000000Z"
    changed = validate_incident_evidence(changed)
    mapped = load("mapping_outcomes")
    scenarios = {
        "canonical_numbers": [load("canonical_numbers"), network],
        "canonical_numbers_reversed": [network, load("canonical_numbers")],
        "encoding_and_precision": [edge_document(network), protect],
        "products": [network, protect],
        "products_reversed": [protect, network],
        "identical_documents_count_once": [network, protect, network],
        "overlapping_identical_sources": [full, network],
        "budget_exhaustion_carried": [spent, protect],
        "mixed_failures": [
            protect,
            *[
                failure(network, kind)
                for kind in (
                    "auth_failed",
                    "permission_denied",
                    "timeout",
                    "unsupported",
                    "parse_failed",
                    "unavailable",
                )
            ],
        ],
        "total_failure": [failure(network, "auth_failed"), failure(network, "timeout")],
        "conflicting_source_ids": [conflicting, changed],
        "mapping_union": [
            split(mapped, "network", mappings=mapped.mappings[:1], use_document_mappings=False),
            split(mapped, "protect", mappings=mapped.mappings[1:], use_document_mappings=False),
        ],
    }
    result = {}
    for name, documents in scenarios.items():
        value = {"inputs": [evidence_to_json(doc) for doc in documents]}
        try:
            value["expected"] = evidence_to_json(combine_incident_evidence(documents))
        except ValueError:
            if name != "conflicting_source_ids":
                raise
            value["error"] = True
        result[name] = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if fixtures differ from Python reference")
    args = parser.parse_args()
    target = ROOT / "combine"
    values = fixtures()
    if args.check:
        stale = [
            name
            for name, content in values.items()
            if not (target / f"{name}.json").exists() or (target / f"{name}.json").read_text() != content
        ]
        stale.extend(path.stem for path in target.glob("*.json") if path.stem not in values)
        if stale:
            parser.exit(1, f"Combine fixtures drifted: {', '.join(stale)}\n")
        print(f"{len(values)} combine fixtures match Python reference")
    else:
        target.mkdir(exist_ok=True)
        for name, content in values.items():
            (target / f"{name}.json").write_text(content)


if __name__ == "__main__":
    main()
