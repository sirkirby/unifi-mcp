"""Drive the shared incident-evidence golden corpus through the Core normalizers.

Each case under ``tests/fixtures/incident_evidence/cases/`` holds an ``input``
(per-source raw payloads exactly as a tool or manager returns them, the tool
arguments under ``args``, and what the collector captured around the call
under ``capture``: request start time, answering API path, server defaults)
and the ``expected`` normalized evidence set. Other consumers, such as the
worker, read the same files and must produce the same output. Cases under
``invalid/`` are evidence sets that consumers must reject.

Regenerate expected outputs and the schema artifact after an intentional
contract change, then review the diff:

    UNIFI_UPDATE_INCIDENT_GOLDEN=1 uv run --package unifi-core pytest \
        packages/unifi-core/tests/test_incident_evidence_golden.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from unifi_core.incident_evidence import (
    Budgets,
    IncidentEvidence,
    MappingAssertion,
    Product,
    Scope,
    SourceContext,
    SourceEvidence,
    SourceFailure,
    TimeWindow,
    assemble_incident_evidence,
    format_utc,
    parse_utc,
    source_failed,
)
from unifi_core.network import incident_evidence as network
from unifi_core.protect import incident_evidence as protect

CORPUS_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "incident_evidence"
CASES_DIR = CORPUS_DIR / "cases"
SCHEMA_PATH = CORPUS_DIR / "incident-evidence.v1.schema.json"
UPDATE_ENV = "UNIFI_UPDATE_INCIDENT_GOLDEN"


def case_paths() -> list[Path]:
    return sorted(CASES_DIR.glob("*.json"))


def load_case(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _context(window: TimeWindow, spec: dict[str, Any]) -> SourceContext:
    tool = spec["tool"]
    collected_at = parse_utc(spec["collected_at"])
    args = dict(spec.get("args", {}))
    scope = dict(spec.get("scope", {}))
    if "source_id" in spec:
        scope["source_id"] = spec["source_id"]
    capture = dict(spec.get("capture", {}))
    if "request_started_at" in capture:
        capture["request_started_at"] = parse_utc(capture["request_started_at"])
    if tool == network.LIST_EVENTS_TOOL:
        context = network.network_events_context(
            requested_window=window, collected_at=collected_at, **capture, **args, **scope
        )
    elif tool == network.LIST_ALARMS_TOOL:
        context = network.network_alarms_context(
            requested_window=window, collected_at=collected_at, **capture, **args, **scope
        )
    elif tool in protect.TOOL_RECORD_PATHS:
        context = protect.protect_events_context(
            requested_window=window, collected_at=collected_at, source_tool=tool, **capture, **args, **scope
        )
    elif tool == "access_list_events":
        context = SourceContext(
            source_id=scope.pop("source_id", "access.events"),
            product=Product.ACCESS,
            api_family=None,
            source_tool=tool,
            scope=Scope(**scope),
            query=args,
            collected_at=format_utc(collected_at),
            requested_window=window,
        )
    else:
        raise ValueError(f"unknown tool in corpus: {tool}")
    overrides = spec.get("context_overrides")
    if overrides:
        context = SourceContext.model_validate({**context.model_dump(), **overrides})
    return context


def _source(window: TimeWindow, spec: dict[str, Any]) -> SourceEvidence:
    context = _context(window, spec)
    failure = SourceFailure.model_validate(spec["failure"]) if spec.get("failure") else None
    adapter = spec["adapter"]
    budget_exhausted = bool(spec.get("budget_exhausted", False))
    if adapter == "failed":
        assert failure is not None, "failed sources name their failure"
        return source_failed(context, failure)
    is_network = context.product is Product.NETWORK
    if adapter == "tool_response":
        assert failure is None, "tool responses carry their own success flag"
        normalize = network.normalize_network_tool_response if is_network else protect.normalize_protect_tool_response
        return normalize(spec["payload"], context, budget_exhausted=budget_exhausted)
    if adapter == "records":
        normalize = network.normalize_network_records if is_network else protect.normalize_protect_records
        return normalize(spec["payload"], context, failure=failure, budget_exhausted=budget_exhausted)
    raise ValueError(f"unknown adapter in corpus: {adapter}")


def build_case(case_input: dict[str, Any]) -> IncidentEvidence:
    window = TimeWindow.model_validate(case_input["requested_window"])
    mappings = case_input.get("mappings")
    return assemble_incident_evidence(
        requested_window=window,
        budgets=Budgets.model_validate(case_input["budgets"]),
        sources=[_source(window, spec) for spec in case_input["sources"]],
        mappings=None if mappings is None else [MappingAssertion.model_validate(item) for item in mappings],
    )
