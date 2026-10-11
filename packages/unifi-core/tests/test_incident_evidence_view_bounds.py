"""The client view's output bound: every valid request's view fits one MCP tool result.

Adversarial documents are collected through the SDK decoders at every input
bound the requests accept, and every page of every view, resumed from its
cursor until nothing is left, is measured with the size tests' estimate.
"""

from __future__ import annotations

import json
import os
import random
from typing import Any

import pytest
from pydantic import ValidationError
from unifi_core.incident_collection import (
    LABEL_RULE,
    MAX_LABEL_LENGTH,
    MAX_MAPPING_ID_LENGTH,
    combine_incident_evidence,
    describe_validation_error,
    is_label,
)
from unifi_core.incident_evidence import IncidentEvidence, TimeStatus
from unifi_core.incident_evidence_view import (
    MAX_RECORDS_RETURNED,
    RECORD_TOKEN_LIMIT,
    SOURCE_LABEL_TOKEN_LIMIT,
    TEXT_TOKEN_LIMITS,
    VIEW_TOKEN_BUDGET,
    EvidencePresentation,
    EvidenceViewTooLarge,
    client_view,
    estimated_tokens,
    view_to_json,
)
from unifi_core.network.incident_collection import collect_network_incident_evidence
from unifi_core.network.models.incident_evidence import NetworkIncidentRequest
from unifi_core.protect.models.incident_evidence import ProtectIncidentRequest

from . import test_incident_evidence_golden as golden
from .incident_evidence_adversarial import (
    WINDOW,
    document_as_received,
    largest_location_document,
    network_document,
    protect_document,
    protect_rows,
    text,
    worst_cameras,
    worst_label,
    worst_macs,
    worst_mappings,
)
from .incident_evidence_corpus import CORPUS_DIR, UPDATE_ENV
from .incident_evidence_tokens import tokens_as_sent
from .incident_evidence_worst_case import NOW as WORST_CASE_NOW
from .incident_evidence_worst_case import WINDOW as WORST_CASE_WINDOW
from .incident_evidence_worst_case import _network_row
from .network.sdk_transport import paging_event_manager
from .test_incident_evidence_view import _assert_same_semantics

BOUNDS_DIR = CORPUS_DIR / "view-bounds"
LIMITS = (1, 25, MAX_RECORDS_RETURNED)


def _pages(evidence: IncidentEvidence, limit: int, most: int | None = None) -> list[dict[str, Any]]:
    """The views of ``evidence`` at ``limit``, each resumed from the last one's cursor, up to ``most``."""
    pages: list[dict[str, Any]] = []
    cursor = None
    while most is None or len(pages) < most:
        view = client_view(evidence, max_records_returned=limit, resume_after=cursor)
        _assert_same_semantics(evidence, view)
        pages.append(view_to_json(view))
        cursor = view.record_selection.next_cursor
        if cursor is None:
            break
        assert len(pages) <= len(evidence.records), "every page makes progress"
    return pages


def _assert_bounded(evidence: IncidentEvidence, limit: int) -> None:
    # One-record pages are sampled; larger pages are read to the end.
    pages = _pages(evidence, limit, most=12 if limit == 1 else None)
    seen: list[str] = []
    skipped = 0
    for page in pages:
        sent = tokens_as_sent(page)
        assert sent <= estimated_tokens({"success": True, "data": page}) <= VIEW_TOKEN_BUDGET, sent
        assert all(estimated_tokens(record) <= RECORD_TOKEN_LIMIT for record in page["records"])
        seen += [record["evidence_id"] for record in page["records"]]
        skipped += page["record_selection"]["too_large"]
    # Paging returns every record exactly once, or counts it as too large to cite.
    assert len(seen) == len(set(seen))
    if pages[-1]["record_selection"]["next_cursor"] is None:
        assert len(seen) + skipped == len(evidence.records)


# --- the bound ------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("seed", "records"), [(0, 0), (0, 1), (0, 40), (1, 40), (2, 40), (0, 120)], ids=lambda value: str(value)
)
@pytest.mark.parametrize("shared_time", [False, True], ids=["spread", "one_timestamp"])
async def test_every_page_of_the_largest_location_fits_the_budget(seed: int, records: int, shared_time: bool) -> None:
    evidence = await largest_location_document(random.Random(seed), records=records, shared_time=shared_time)
    assert len(evidence.sources) == 7
    for limit in LIMITS:
        _assert_bounded(evidence, limit)


@pytest.mark.asyncio
async def test_one_largest_citation_always_fits_beside_everything_else() -> None:
    """With nothing collected, what remains of the budget holds the largest citation a view returns."""
    evidence = await largest_location_document(random.Random(0), records=0)
    assert not evidence.records
    view = view_to_json(client_view(evidence))
    assert estimated_tokens({"success": True, "data": view}) + RECORD_TOKEN_LIMIT <= VIEW_TOKEN_BUDGET


@pytest.mark.asyncio
@pytest.mark.parametrize("seed", range(4))
async def test_single_product_documents_fit_the_budget(seed: int) -> None:
    rng = random.Random(seed)
    network = await network_document(rng, records=rng.randrange(1, 400), shared_time=rng.random() < 0.5)
    protect = await protect_document(rng, records_per_camera=rng.randrange(1, 90), cameras=worst_cameras())
    for evidence in (network, protect):
        for limit in LIMITS:
            _assert_bounded(evidence, limit)


@pytest.mark.parametrize("seed", range(20))
def test_the_estimate_never_undercounts_the_size_tests(seed: int) -> None:
    rng = random.Random(seed)

    def value(depth: int) -> Any:
        roll = rng.random()
        if depth > 3 or roll < 0.4:
            return rng.choice(
                [None, True, False, rng.randrange(-(10**12), 10**12), rng.random() * 10 ** rng.randrange(-5, 15), 3.0]
                + [text(rng, rng.randrange(0, 200)) for _ in range(4)]
            )
        if roll < 0.7:
            return [value(depth + 1) for _ in range(rng.randrange(0, 5))]
        return {text(rng, rng.randrange(1, 20)): value(depth + 1) for _ in range(rng.randrange(0, 5))}

    for _ in range(50):
        payload = value(0)
        assert tokens_as_sent(payload) <= estimated_tokens({"success": True, "data": payload})


# --- free text and identifiers --------------------------------------------------------------


@pytest.mark.asyncio
async def test_long_free_text_is_cut_to_a_prefix_and_marked() -> None:
    row = dict(_network_row(1), message_raw=" ~".join(str(i) for i in range(15_000)))
    request = NetworkIncidentRequest(**WORST_CASE_WINDOW)
    evidence = await collect_network_incident_evidence(
        paging_event_manager([row]), request, site="default", now=lambda: WORST_CASE_NOW
    )
    (record,) = evidence.records
    assert len(record.summary) > 90_000
    view = client_view(evidence)
    (shown,) = view.records
    assert shown.truncated == {"summary": len(record.summary)}
    assert record.summary.startswith(shown.summary)
    assert estimated_tokens(shown.summary) - 2 <= TEXT_TOKEN_LIMITS["summary"]
    assert shown.evidence_id == record.evidence_id
    assert tokens_as_sent(view_to_json(view)) < 3_000


@pytest.mark.asyncio
async def test_identifiers_are_never_cut_and_an_uncitable_record_is_counted() -> None:
    rng = random.Random(2)
    cameras = worst_cameras(1)
    rows = protect_rows(rng, 30, cameras, shared_time=True)
    rows[3]["camera"] = "-" * 3_000  # a token per character: over the record limit
    rows[4]["camera"] = "c" * 2_000  # four characters per token: cited in full
    rows[7]["id"] = "p" + "%" * 100  # percent-encoded to 301 characters
    evidence = await protect_document(rng, records_per_camera=30, cameras=cameras, rows=rows)
    long_entities = {r.evidence_id for r in evidence.records if any(len(e.id) > 2_000 for e in r.entities)}
    long_ids = {r.evidence_id for r in evidence.records if len(r.evidence_id) > 256}
    assert long_entities and long_ids
    pages = _pages(evidence, MAX_RECORDS_RETURNED)
    shown = [record for page in pages for record in page["records"]]
    assert not {record["evidence_id"] for record in shown} & (long_entities | long_ids)
    by_id = {record.evidence_id: record for record in evidence.records}
    for record in shown:
        assert record["entity_ids"] == [entity.id for entity in by_id[record["evidence_id"]].entities]
    assert ["c" * 2_000] in [record["entity_ids"] for record in shown]
    assert sum(page["record_selection"]["too_large"] for page in pages) == len(long_entities | long_ids)


# --- what the view repeats from the document -------------------------------------------------

_LABELS = ("controller_id", "site", "location_id", "source_tool")
# Labels beyond request validation, each well over its limit and cut to it.
_LONG_LABELS = {
    "site": "-" * 600,
    "location_id": "~" * 300,
    "controller_id": "fixture-" + "\u00e9" * 300,
    "source_tool": "fixture_" + "x" * 2_000,
}


async def _crowded_document(assertions: int) -> IncidentEvidence:
    """The largest location with long labels and ``assertions`` more assertions, crowding out citations."""
    base = await largest_location_document(random.Random(13), records=5, text_length=600)
    return document_as_received(
        base, labels=_LONG_LABELS, assertion_ids=[f"fixture-{i:03d}" + "~" * 120 for i in range(assertions)]
    )


async def _one_record_document() -> IncidentEvidence:
    return await collect_network_incident_evidence(
        paging_event_manager([_network_row(1)]),
        NetworkIncidentRequest(**WORST_CASE_WINDOW),
        site="default",
        now=lambda: WORST_CASE_NOW,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("site", ["-" * 30_000, worst_label(MAX_LABEL_LENGTH + 1), 'fixture "a"', "fixture\na", ""])
async def test_the_site_is_held_to_the_label_rule_before_any_read(site: str) -> None:
    async def acquire() -> Any:
        raise AssertionError("an invalid site must be refused before the manager is acquired")

    with pytest.raises(ValueError) as caught:
        await collect_network_incident_evidence(acquire, NetworkIncidentRequest(**WINDOW), site=site)
    assert str(caught.value) == f"site: must be 1-{MAX_LABEL_LENGTH} characters {LABEL_RULE}"
    evidence = await collect_network_incident_evidence(
        paging_event_manager([]), NetworkIncidentRequest(**WINDOW), site=worst_label()
    )
    assert evidence.sources[0].scope.site == worst_label()


@pytest.mark.asyncio
async def test_labels_beyond_request_validation_are_cut_and_marked() -> None:
    """A 30,000-character site, as a document from outside request validation could carry it."""
    evidence = document_as_received(await _one_record_document(), labels={"site": "-" * 30_000})
    view = view_to_json(client_view(evidence))
    (source,) = view["sources"]
    assert source["truncated"] == {"site": 30_000}
    assert source["scope"]["site"] == "-" * SOURCE_LABEL_TOKEN_LIMIT
    assert source["scope"]["location_id"] == "fixture-location-a" and source["outcome"] == "complete"
    assert len(view["records"]) == 1 and view["record_selection"]["limited_by"] is None
    assert tokens_as_sent(view) < 3_000


@pytest.mark.asyncio
async def test_a_citation_that_cannot_fit_beside_the_sources_is_counted_too_large() -> None:
    """The first citation has no exemption: with the budget nearly spent by sources and assertions, none fits."""
    evidence = await _crowded_document(16)
    view = client_view(evidence, max_records_returned=MAX_RECORDS_RETURNED)
    selection = view.record_selection
    assert not view.records and selection.too_large == len(evidence.records) == selection.omitted.total
    assert selection.limited_by is None and selection.next_cursor is None
    assert estimated_tokens({"success": True, "data": view_to_json(view)}) <= VIEW_TOKEN_BUDGET


@pytest.mark.asyncio
async def test_a_view_that_cannot_hold_its_sources_and_assertions_is_refused() -> None:
    base = await _one_record_document()
    for evidence in (
        document_as_received(base, assertion_ids=["fixture-" + "~" * 8_000] * 3),
        document_as_received(base, failed_sources=150),
    ):
        with pytest.raises(EvidenceViewTooLarge) as caught:
            client_view(evidence)
        message = str(caught.value)
        assert message.startswith(f"the evidence view would exceed its {VIEW_TOKEN_BUDGET}-token output budget")
        assert f"sources: {len(evidence.sources)}, mapping assertions: {len(evidence.mappings or ())}" in message
        assert "detail=full" in message and "~" not in message and "fixture" not in message
        assert EvidencePresentation(detail="full").render(evidence)["sources"]


@pytest.mark.asyncio
async def test_any_document_has_a_view_within_the_budget_or_a_bounded_refusal() -> None:
    """Every free-text input at its largest accepted size, and beyond it where a document can carry more.

    The bases are collected at every request bound (costliest controller text,
    labels, MACs, cameras and assertions); each draw then puts oversized
    labels in every source and record, adds assertions with oversized
    identifiers and adds sources, as a relay outside request validation could.
    """
    bases = [
        await largest_location_document(random.Random(seed), records=records, shared_time=seed == 1)
        for seed, records in ((0, 0), (1, 40), (2, 8))
    ]
    rng = random.Random(794)
    outcomes = {"view": 0, "cut": 0, "refused": 0, "too_large": 0}
    for _ in range(48):
        base = rng.choice(bases)
        labels = {
            field: text(rng, rng.choice((0, MAX_LABEL_LENGTH, 4 * SOURCE_LABEL_TOKEN_LIMIT + 1, 30_000)))
            for field in rng.sample(_LABELS, rng.randrange(0, len(_LABELS) + 1))
        }
        assertion_ids = [
            "fixture-" + text(rng, rng.choice((1, MAX_MAPPING_ID_LENGTH, 3_000)))
            for _ in range(rng.choice((0, 0, 8, 40)))
        ]
        failed = rng.choice((0, 0, 20, 150))
        evidence = document_as_received(base, labels=labels, assertion_ids=assertion_ids, failed_sources=failed)
        try:
            pages = _pages(evidence, rng.choice(LIMITS), most=4)
        except EvidenceViewTooLarge as exc:
            # Labels are cut, never refused: only sources and assertions can fill the budget.
            assert assertion_ids or failed, labels.keys()
            assert len(str(exc)) < 400 and "fixture" not in str(exc)
            outcomes["refused"] += 1
            continue
        outcomes["view"] += 1
        for page in pages:
            assert tokens_as_sent(page) <= estimated_tokens({"success": True, "data": page}) <= VIEW_TOKEN_BUDGET
            outcomes["cut"] += any(source["truncated"] for source in page["sources"])
            outcomes["too_large"] += page["record_selection"]["too_large"]
    assert all(outcomes.values()), outcomes


# --- continuation ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_records_sharing_one_timestamp_page_without_repeats() -> None:
    rows = [dict(_network_row(index), timestamp=1786190401000) for index in range(60)]
    evidence = await collect_network_incident_evidence(
        paging_event_manager(rows),
        NetworkIncidentRequest(**WORST_CASE_WINDOW),
        site="default",
        now=lambda: WORST_CASE_NOW,
    )
    in_window = [r for r in evidence.records if r.time.status is TimeStatus.IN_WINDOW]
    assert len(in_window) == 60 and len({r.time.utc for r in in_window}) == 1
    # Thirty stop at the record limit; fifty at the output budget.
    for limit, stop in ((30, "max_records_returned"), (50, "output_budget")):
        first, second = _pages(evidence, limit)
        assert first["record_selection"]["limited_by"] == stop
        assert second["record_selection"]["before_resume"] == first["record_selection"]["returned"]
        assert second["record_selection"]["next_cursor"] is None
        shown = [record["evidence_id"] for page in (first, second) for record in page["records"]]
        assert sorted(shown) == sorted(record.evidence_id for record in in_window)


def test_presentation_takes_a_cursor_for_views_only() -> None:
    cursor = "0|2026-08-08T12:00:00.000000Z|network.events|str|66b4"
    assert EvidencePresentation(resume_after=cursor).resume_after == cursor
    with pytest.raises(ValidationError):
        EvidencePresentation(detail="full", resume_after=cursor)


# --- request bounds -------------------------------------------------------------------------


def _assertion(entity_id: str, target_id: str = "fixture-location-a", **entity: Any) -> dict[str, Any]:
    return {
        "entity": {"kind": "network_device", "id_kind": "mac", "id": entity_id, **entity},
        "target": {"kind": "location", "id_kind": "location_id", "id": target_id},
        "source": "operator_input",
    }


@pytest.mark.parametrize("model", [NetworkIncidentRequest, ProtectIncidentRequest])
def test_requests_bound_labels_and_mapping_identifiers(model) -> None:
    assert model(**WINDOW, location_id=worst_label(), mappings=worst_mappings(worst_macs(1)[0], worst_cameras()))
    for rejected in (
        {"location_id": worst_label(MAX_LABEL_LENGTH + 1)},
        {"location_id": 'fixture "a"'},
        {"location_id": "fixture\na"},
        {"mappings": [_assertion("02:00:00:00:00:01", " ~".join(str(i) for i in range(15_000)))]},
        {"mappings": [_assertion("x" * (MAX_MAPPING_ID_LENGTH + 1))]},
        {"mappings": [_assertion("02:00:00:00:00:01", "fixture\\a")]},
        {"mappings": [_assertion("02:00:00:00:00:01", role="uplink")]},
    ):
        with pytest.raises(ValidationError) as caught:
            model(**WINDOW, **rejected)
        message = describe_validation_error(caught.value, model)
        assert "14999" not in message and "fixture" not in message and "uplink" not in message


def test_labels_refuse_only_what_json_escapes() -> None:
    assert is_label("Front office é \U0001f600 #2 (east)")
    assert not any(is_label(f"a{c}b") for c in ('"', "\\", "\x00", "\x1f", "\x7f"))


# --- golden bounded views for other consumers -----------------------------------------------


async def _bound_cases() -> dict[str, tuple[IncidentEvidence, tuple[int, ...]]]:
    """Small documents that still reach every limit: each case and the record limits its views use.

    A case with no limits is refused.
    """
    rng = random.Random(11)
    network = await network_document(rng, records=10, shared_time=True, text_length=1_500)
    rows = protect_rows(rng, 5, worst_cameras(2), shared_time=False)
    rows[0]["camera"] = "-" * 3_000
    rows[1]["id"] = "p" + "%" * 100
    protect = await protect_document(rng, records_per_camera=5, cameras=worst_cameras(2), rows=rows)
    largest = await largest_location_document(random.Random(12), records=10, text_length=600)
    # Too little of the budget is left for the first citations examined.
    crowded = await _crowded_document(12)
    refused = document_as_received(await _one_record_document(), assertion_ids=["fixture-" + "~" * 8_000] * 3)
    return {
        "long_text_and_identifiers": (combine_incident_evidence([network, protect]), (3, MAX_RECORDS_RETURNED)),
        "output_budget": (largest, (MAX_RECORDS_RETURNED,)),
        "oversized_skeleton": (crowded, (MAX_RECORDS_RETURNED,)),
        "skeleton_refusal": (refused, ()),
    }


@pytest.mark.asyncio
async def test_bounded_view_fixtures_match_the_projection() -> None:
    """Python-generated documents and every page of their views, for the worker's TypeScript port."""
    cases = await _bound_cases()
    updating = os.environ.get(UPDATE_ENV) == "1"
    if updating:
        BOUNDS_DIR.mkdir(exist_ok=True)
    else:
        assert {path.stem for path in BOUNDS_DIR.glob("*.json")} == set(cases)
    stops = set()
    too_large = truncated = cut_labels = 0
    for name, (evidence, limits) in cases.items():
        fixture: dict[str, Any] = {"case": name, "evidence": evidence.model_dump(mode="json", by_alias=True)}
        if not limits:
            with pytest.raises(EvidenceViewTooLarge) as caught:
                client_view(evidence)
            fixture["refusal"] = str(caught.value)
        views = []
        for limit in limits:
            cursor = None
            for page in _pages(evidence, limit):
                views.append({"max_records_returned": limit, "resume_after": cursor, "expected": page})
                cursor = page["record_selection"]["next_cursor"]
                stops.add(page["record_selection"]["limited_by"])
                too_large += page["record_selection"]["too_large"]
                truncated += sum(bool(record["truncated"]) for record in page["records"])
                cut_labels += sum(bool(source["truncated"]) for source in page["sources"])
        if limits:
            fixture["views"] = views
        target = BOUNDS_DIR / f"{name}.json"
        if updating:
            target.write_text(json.dumps(fixture, ensure_ascii=True, separators=(",", ":")) + "\n")
        assert json.loads(target.read_text()) == fixture
    assert stops == {"max_records_returned", "output_budget", None}, "the fixtures reach every limit"
    assert too_large and truncated and cut_labels


@pytest.mark.parametrize("path", sorted(BOUNDS_DIR.glob("*.json")), ids=lambda path: path.stem)
def test_bounded_view_fixtures_contain_only_synthetic_identifiers(path) -> None:
    golden.test_fixture_contains_only_synthetic_identifiers(path)
