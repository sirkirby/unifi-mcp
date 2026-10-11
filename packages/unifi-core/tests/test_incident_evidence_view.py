"""The bounded client view: golden views, schema drift, unchanged coverage semantics and size."""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any

import jsonschema
import pydantic_core
import pytest
from pydantic import ValidationError
from unifi_core.incident_evidence import (
    IncidentEvidence,
    TimeStatus,
    evidence_to_json,
    validate_incident_evidence,
)
from unifi_core.incident_evidence_view import (
    DEFAULT_MAX_RECORDS_RETURNED,
    MAX_RECORDS_RETURNED,
    EvidencePresentation,
    IncidentEvidenceView,
    ViewSource,
    canonical_view_json,
    client_view,
    incident_evidence_view_json_schema,
    view_to_json,
)

from .incident_evidence_corpus import CORPUS_DIR, UPDATE_ENV, case_paths, load_case
from .incident_evidence_worst_case import network_worst_case, protect_worst_case

UPDATING = os.environ.get(UPDATE_ENV) == "1"
VIEWS_DIR = CORPUS_DIR / "views"
VIEW_SCHEMA_PATH = CORPUS_DIR / "incident-evidence-view.v1.schema.json"
# A small limit makes every case with records exercise omission.
LIMITS = (DEFAULT_MAX_RECORDS_RETURNED, 2)


def _dump(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _evidence(path: Path) -> IncidentEvidence:
    return validate_incident_evidence(load_case(path)["expected"])


def _views(path: Path) -> list[dict[str, Any]]:
    evidence = _evidence(path)
    return [
        {"max_records_returned": limit, "expected": view_to_json(client_view(evidence, max_records_returned=limit))}
        for limit in LIMITS
    ]


# --- golden views -------------------------------------------------------------------


def test_every_golden_case_has_a_view_fixture() -> None:
    if UPDATING:
        VIEWS_DIR.mkdir(exist_ok=True)
        for stale in set(VIEWS_DIR.glob("*.json")) - {VIEWS_DIR / p.name for p in case_paths()}:
            stale.unlink()
        return
    assert {p.name for p in VIEWS_DIR.glob("*.json")} == {p.name for p in case_paths()}


@pytest.mark.parametrize("path", case_paths(), ids=lambda p: p.stem)
def test_golden_view_matches_projection(path: Path) -> None:
    fixture = {"case": path.stem, "views": _views(path)}
    target = VIEWS_DIR / path.name
    if UPDATING:
        target.write_text(json.dumps(fixture, indent=2, ensure_ascii=True) + "\n")
    assert json.loads(target.read_text()) == fixture


def test_view_schema_artifact_has_not_drifted() -> None:
    generated = _dump(incident_evidence_view_json_schema())
    if UPDATING:
        VIEW_SCHEMA_PATH.write_text(generated)
    assert VIEW_SCHEMA_PATH.read_text() == generated, (
        f"incident evidence view schema drifted; regenerate with {UPDATE_ENV}=1 and review the diff"
    )


def test_view_schema_artifact_is_versioned() -> None:
    schema = json.loads(VIEW_SCHEMA_PATH.read_text())
    assert schema["$id"] == "urn:unifi-mcp:unifi-incident-evidence-view:v1"
    assert schema["properties"]["schema_version"]["const"] == 1
    assert schema["properties"]["evidence_schema_version"]["const"] == 1
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize("path", case_paths(), ids=lambda p: p.stem)
def test_golden_views_validate_and_are_canonical(path: Path) -> None:
    schema = json.loads(VIEW_SCHEMA_PATH.read_text())
    for item in json.loads((VIEWS_DIR / path.name).read_text())["views"]:
        jsonschema.validate(item["expected"], schema)
        view = IncidentEvidenceView.model_validate(item["expected"])
        assert json.loads(canonical_view_json(view)) == item["expected"]


# --- the view states coverage exactly as the document does ---------------------------


def _assert_same_semantics(evidence: IncidentEvidence, view: IncidentEvidenceView) -> None:
    assert view.overall is evidence.overall
    assert view.coverage_complete is evidence.coverage_complete
    assert view.requested_window == evidence.requested_window
    assert view.budgets == evidence.budgets
    assert view.mappings == evidence.mappings
    assert [s.source_id for s in view.sources] == [s.source_id for s in evidence.sources]
    for shown, source in zip(view.sources, evidence.sources, strict=True):
        for name in ViewSource.model_fields:
            assert getattr(shown, name) == getattr(source, name), name
    selection = view.record_selection
    statuses = [record.time.status for record in evidence.records]
    assert selection.collected.total == len(evidence.records)
    assert selection.collected.in_window == statuses.count(TimeStatus.IN_WINDOW)
    by_id = {record.evidence_id: record for record in evidence.records}
    for shown in view.records:
        record = by_id[shown.evidence_id]
        assert shown.product is record.provenance.product
        assert shown.source_tool == record.provenance.source_tool
        assert shown.source_record_id == record.provenance.source_record_id
        assert shown.time.status is record.time.status and shown.time.utc == record.time.utc
        assert shown.time.original_value == record.time.original_value
        assert (shown.event_type, shown.summary) == (record.event_type, record.summary)
        assert shown.entity_ids == tuple(entity.id for entity in record.entities)
        assert shown.mapping.status is record.mapping.status
        assert shown.mapping.target_ids == tuple(target.id for target in record.mapping.targets)


@pytest.mark.parametrize("path", case_paths(), ids=lambda p: p.stem)
@pytest.mark.parametrize("limit", [1, 2, DEFAULT_MAX_RECORDS_RETURNED, MAX_RECORDS_RETURNED])
def test_view_keeps_coverage_and_failure_semantics(path: Path, limit: int) -> None:
    evidence = _evidence(path)
    _assert_same_semantics(evidence, client_view(evidence, max_records_returned=limit))


@pytest.mark.asyncio
@pytest.mark.parametrize("build", [network_worst_case, protect_worst_case], ids=["network", "protect"])
async def test_worst_case_view_keeps_coverage_and_failure_semantics(build) -> None:
    evidence = await build()
    _assert_same_semantics(evidence, client_view(evidence))


# --- record selection -------------------------------------------------------------------


def test_in_window_records_come_first_and_omission_says_where_to_resume() -> None:
    evidence = _evidence(Path(CORPUS_DIR / "cases" / "malformed_timestamps.json"))
    view = client_view(evidence, max_records_returned=1)
    (shown,) = view.records
    assert shown.time.status is TimeStatus.IN_WINDOW
    assert view.record_selection.omitted.untimed == 9
    assert view.record_selection.omitted_in_window_from_utc is None
    assert view.record_selection.omission == "presentation_limit"

    evidence = _evidence(Path(CORPUS_DIR / "cases" / "network_protect_real_shapes.json"))
    view = client_view(evidence, max_records_returned=2)
    in_window = [r for r in evidence.records if r.time.status is TimeStatus.IN_WINDOW]
    assert [r.evidence_id for r in view.records] == [r.evidence_id for r in in_window[:2]]
    assert view.record_selection.omitted_in_window_from_utc == in_window[2].time.utc


def test_untimed_records_are_kept_before_out_of_window_records() -> None:
    evidence = _evidence(Path(CORPUS_DIR / "cases" / "out_of_window_boundaries.json"))
    statuses = {r.time.status for r in evidence.records}
    assert TimeStatus.OUT_OF_WINDOW in statuses
    in_window = sum(r.time.status is TimeStatus.IN_WINDOW for r in evidence.records)
    view = client_view(evidence, max_records_returned=in_window + 1)
    leftover = [r for r in view.records if r.time.status is not TimeStatus.IN_WINDOW]
    untimed = [r for r in evidence.records if r.time.status not in (TimeStatus.IN_WINDOW, TimeStatus.OUT_OF_WINDOW)]
    assert [r.time.status for r in leftover] == ([untimed[0].time.status] if untimed else [TimeStatus.OUT_OF_WINDOW])


def test_view_is_deterministic_and_never_changes_the_document() -> None:
    evidence = _evidence(Path(CORPUS_DIR / "cases" / "mapping_outcomes.json"))
    before = evidence_to_json(evidence)
    assert view_to_json(client_view(evidence)) == view_to_json(client_view(evidence))
    assert evidence_to_json(evidence) == before


# --- size ---------------------------------------------------------------------------------

# MCP servers send a dict result as JSON indented by two spaces. Tokens are
# estimated conservatively: every whitespace run and punctuation character is
# a token, letters count one token per four and digits one per three.
_TOKEN_PARTS = re.compile(r"[A-Za-z]+|[0-9]+|\s+|[^\sA-Za-z0-9]")
DEFAULT_VIEW_TOKEN_LIMIT = 16_000
MAX_VIEW_TOKEN_LIMIT = 24_000


def _estimated_tokens(payload: dict[str, Any]) -> int:
    text = pydantic_core.to_json({"success": True, "data": payload}, indent=2).decode()
    total = 0
    for part in _TOKEN_PARTS.findall(text):
        if part[0].isalpha():
            total += math.ceil(len(part) / 4)
        elif part[0].isdigit():
            total += math.ceil(len(part) / 3)
        else:
            total += 1
    return total


@pytest.mark.asyncio
@pytest.mark.parametrize("build", [network_worst_case, protect_worst_case], ids=["network", "protect"])
async def test_default_view_of_the_largest_default_budget_document_fits_a_client(build) -> None:
    evidence = await build()
    assert len(evidence.records) >= 990, "the worst case must fill the default events budget"
    full = _estimated_tokens(evidence_to_json(evidence))
    default = _estimated_tokens(EvidencePresentation().render(evidence))
    largest = _estimated_tokens(EvidencePresentation(max_records_returned=MAX_RECORDS_RETURNED).render(evidence))
    assert full > 200_000
    assert default <= DEFAULT_VIEW_TOKEN_LIMIT, default
    assert largest <= MAX_VIEW_TOKEN_LIMIT, largest


# --- presentation arguments -----------------------------------------------------------------


def test_full_detail_returns_the_contract_document() -> None:
    evidence = _evidence(Path(CORPUS_DIR / "cases" / "budget_exhaustion.json"))
    assert EvidencePresentation(detail="full").render(evidence) == evidence_to_json(evidence)
    view = EvidencePresentation().render(evidence)
    assert view["schema"] == "unifi-incident-evidence-view"
    assert view["record_selection"]["max_records_returned"] == DEFAULT_MAX_RECORDS_RETURNED


@pytest.mark.parametrize(
    "arguments",
    [
        {"detail": "full", "max_records_returned": 5},
        {"max_records_returned": 0},
        {"max_records_returned": MAX_RECORDS_RETURNED + 1},
        {"detail": "summary"},
    ],
)
def test_invalid_presentation_is_rejected(arguments: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        EvidencePresentation(**arguments)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda v: v.update(overall="empty", coverage_complete=True), "overall"),
        (lambda v: v["record_selection"]["omitted"].update(total=0, in_window=0), "add up"),
        (lambda v: v["records"].pop(), "returned counts"),
        (lambda v: v["sources"].reverse(), "sorted"),
    ],
)
def test_view_contradictions_are_rejected(change, message: str) -> None:
    view = view_to_json(
        client_view(_evidence(Path(CORPUS_DIR / "cases" / "network_protect_real_shapes.json")), max_records_returned=3)
    )
    change(view)
    with pytest.raises(ValidationError, match=message):
        IncidentEvidenceView.model_validate(view)


def test_requests_refuse_more_sources_or_assertions_than_a_view_can_state() -> None:
    from unifi_core.incident_collection import MAX_MAPPINGS
    from unifi_core.network.models.incident_evidence import NetworkIncidentRequest
    from unifi_core.protect.models.incident_evidence import MAX_CAMERA_IDS, ProtectIncidentRequest

    window = {"start": "2026-08-08T12:00:00Z", "end": "2026-08-08T13:00:00Z"}
    cameras = [f"cam-fixture-{index:04d}" for index in range(MAX_CAMERA_IDS + 1)]
    assert ProtectIncidentRequest(**window, camera_ids=cameras[:-1]).camera_ids
    with pytest.raises(ValidationError):
        ProtectIncidentRequest(**window, camera_ids=cameras)
    assertion = {
        "entity": {"kind": "network_device", "id_kind": "mac", "id": "02:00:00:00:00:01"},
        "target": {"kind": "camera", "id_kind": "protect_camera_id", "id": "cam-fixture-0001"},
        "source": "operator_input",
    }
    assert NetworkIncidentRequest(**window, mappings=[assertion] * MAX_MAPPINGS).mappings
    with pytest.raises(ValidationError):
        NetworkIncidentRequest(**window, mappings=[assertion] * (MAX_MAPPINGS + 1))
