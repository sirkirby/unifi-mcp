"""Adversarial evidence documents at every input bound the requests accept.

Collected by the real collectors through the SDKs' own decoders, with only
the HTTP exchange replaced. Every string a controller returns is drawn from
the characters JSON escapes or a tokenizer treats apart (quotes,
backslashes, control characters, whitespace, punctuation, letters, digits
and two- to four-byte characters), often in long runs, and every string a
caller supplies is as long as request validation allows. A seeded generator
keeps every run reproducible.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

from unifi_core.incident_collection import (
    MAX_FILTER_IDS,
    MAX_LABEL_LENGTH,
    MAX_MAPPING_ID_LENGTH,
    MAX_MAPPINGS,
    combine_incident_evidence,
)
from unifi_core.incident_evidence import (
    Budgets,
    BudgetUsage,
    FailureKind,
    IncidentEvidence,
    MappingAssertion,
    Product,
    Scope,
    SourceContext,
    SourceEvidence,
    SourceFailure,
    assemble_incident_evidence,
    format_utc,
    parse_utc,
    source_failed,
)
from unifi_core.network.incident_collection import collect_network_incident_evidence
from unifi_core.network.models.incident_evidence import NetworkIncidentRequest
from unifi_core.protect.incident_collection import collect_protect_incident_evidence
from unifi_core.protect.models.incident_evidence import MAX_CAMERA_IDS, ProtectIncidentRequest

from .network.sdk_transport import paging_event_manager
from .protect.sdk_transport import sdk_protect_event_manager

NOW = parse_utc("2026-08-08T13:05:00.000000Z")
WINDOW = {"start": "2026-08-08T12:00:00Z", "end": "2026-08-08T13:00:00Z"}
START_MS = 1786190400000
SPAN_MS = 3_600_000


def _frozen() -> float:
    """A clock that never advances, so elapsed usage, like everything else, is reproducible."""
    return 0.0


# Controller text: every character class JSON or a tokenizer treats apart,
# often repeated in long runs: escaped characters, whitespace (ASCII,
# no-break and ideographic), punctuation, letters, digits, and two-, three-
# and four-byte characters.
_TEXT = (
    '"', "\\", "\x01", "\n", "\t", "\U0001f600", "\U00020000", "é", "\u4e2d", " ", " ", "\u00a0", "\u3000",
    "a", "7", "~", "%", "|",
)  # fmt: skip
_RUNS = (1,) * 12 + (16, 300)


def text(rng: random.Random, length: int, alphabet: tuple[str, ...] = _TEXT) -> str:
    """``length`` characters from ``alphabet``, some repeated in runs."""
    characters: list[str] = []
    while len(characters) < length:
        characters += rng.choice(alphabet) * rng.choice(_RUNS)
    return "".join(characters[:length])


def worst_label(length: int = MAX_LABEL_LENGTH, prefix: str = "", character: str = "~") -> str:
    """A caller label as long as validation allows.

    A ``~`` is a token of its own, so the default label is never cut; a
    four-byte ``character`` makes it as costly as validation allows.
    """
    return prefix + character * (length - len(prefix))


def worst_macs(count: int = MAX_FILTER_IDS) -> list[str]:
    # Alternating digits and hex letters split every pair into two runs.
    return [f"0a:1b:2c:3d:{index >> 4:x}e:{index & 0xF:x}f" for index in range(count)]


def worst_cameras(count: int = MAX_CAMERA_IDS) -> list[str]:
    # Punctuation is the costliest the camera ID rule allows.
    return [f"{index}{'-' * 63}" for index in range(count)]


def worst_mappings(device: str, cameras: list[str], label_character: str = "~") -> list[dict]:
    """The most assertions a request accepts, every identifier as long and costly as allowed.

    The device maps to every target, so a record naming it is ambiguous between them all.
    """
    targets = [{"kind": "camera", "id_kind": "protect_camera_id", "id": camera} for camera in cameras]
    while len(targets) < MAX_MAPPINGS:
        prefix = f"{len(targets):02d}"
        target_id = worst_label(MAX_MAPPING_ID_LENGTH, prefix, label_character)
        targets.append({"kind": "location", "id_kind": "location_id", "id": target_id})
    entity = {"kind": "network_station", "id_kind": "mac", "id": device}
    return [{"entity": entity, "target": target, "source": "product_inventory"} for target in targets]


def network_rows(rng: random.Random, count: int, *, device: str, shared_time: bool, text_length: int) -> list[dict]:
    rows = []
    for index in range(count):
        record_id = f"{index:04d}" + (text(rng, rng.choice((0, 24, 400))) if rng.random() < 0.3 else "")
        rows.append(
            {
                "id": record_id,
                "key": text(rng, rng.randrange(1, 200)),
                "event": "EVT",
                "category": "CLIENT_DEVICES",
                "severity": "MEDIUM",
                "timestamp": START_MS + (0 if shared_time else rng.randrange(-60_000, SPAN_MS + 60_000)),
                "message_raw": text(rng, rng.randrange(0, text_length)),
                "parameters": {
                    "DEVICE": {"id": device, "name": text(rng, 30)},
                    "CLIENT": {"id": f"02:00:00:00:{index >> 8:02x}:{index & 0xFF:02x}", "name": text(rng, 30)},
                },
            }
        )
    return sorted(rows, key=lambda row: -row["timestamp"])


async def network_document(
    rng: random.Random,
    *,
    records: int,
    shared_time: bool = False,
    text_length: int = 20_000,
    location_id: str | None = None,
    site: str | None = None,
    mappings: list[dict] | None = None,
    device_macs: list[str] | None = None,
) -> IncidentEvidence:
    device = (device_macs or worst_macs(1))[0]
    rows = network_rows(rng, records, device=device, shared_time=shared_time, text_length=text_length)
    request = NetworkIncidentRequest(
        **WINDOW,
        location_id=location_id,
        mappings=mappings,
        device_macs=device_macs,
        max_events=10_000,
        max_calls=100,
    )
    with patch("unifi_core.network.managers.event_manager.time.time", return_value=NOW.timestamp()):
        return await collect_network_incident_evidence(
            paging_event_manager(rows), request, site=site or "default", clock=_frozen, now=lambda: NOW
        )


def protect_rows(rng: random.Random, count: int, cameras: list[str], *, shared_time: bool) -> list[dict]:
    rows = []
    for index in range(count):
        roll = rng.random()
        if roll < 0.1:
            start: object = text(rng, rng.randrange(1, 300))
        elif roll < 0.15:
            start = None
        else:
            start = START_MS + (0 if shared_time else rng.randrange(-60_000, SPAN_MS + 60_000))
        camera = rng.choice(cameras) if rng.random() < 0.9 else text(rng, rng.choice((10, 2_000)))
        rows.append(
            {
                "id": f"p{index:04d}" + (text(rng, 300) if rng.random() < 0.05 else ""),
                "type": text(rng, rng.randrange(1, 100)),
                "camera": camera,
                "start": start,
                "end": None,
                "score": rng.random() * 100,
                "smartDetectTypes": [text(rng, rng.randrange(0, 4_000)) for _ in range(rng.randrange(0, 4))],
            }
        )
    return rows


async def protect_document(
    rng: random.Random,
    *,
    records_per_camera: int,
    cameras: list[str],
    shared_time: bool = False,
    location_id: str | None = None,
    mappings: list[dict] | None = None,
    rows: list[dict] | None = None,
) -> IncidentEvidence:
    """Every camera's source answered by one short page, so each is read in one request."""
    pages = [
        rows if rows is not None else protect_rows(rng, records_per_camera, cameras, shared_time=shared_time)
        for _ in cameras or [None]
    ]
    request = ProtectIncidentRequest(
        **WINDOW, camera_ids=cameras, location_id=location_id, mappings=mappings, max_events=10_000, max_calls=100
    )
    return await collect_protect_incident_evidence(
        sdk_protect_event_manager(*pages), request, clock=_frozen, now=lambda: NOW + timedelta(0)
    )


def unsupported_access_document(*, location_id: str | None, mappings: list[dict] | None) -> IncidentEvidence:
    """The source the relay adds when Access is requested (no Access evidence tool exists)."""
    request = NetworkIncidentRequest(
        **WINDOW, location_id=location_id, mappings=mappings, max_events=10_000, max_calls=100
    )
    context = SourceContext(
        source_id="access.incident_evidence",
        product=Product.ACCESS,
        api_family=None,
        scope=Scope(location_id=location_id),
        query={"start": WINDOW["start"], "end": WINDOW["end"]},
        collected_at=format_utc(datetime(2026, 8, 8, 13, 5, tzinfo=timezone.utc)),
        requested_window=request.window,
    )
    return assemble_incident_evidence(
        requested_window=request.window,
        budgets=Budgets(limits=request.limits, usage=BudgetUsage()),
        mappings=request.mappings,
        sources=[source_failed(context, SourceFailure(kind=FailureKind.UNSUPPORTED))],
    )


async def largest_location_document(
    rng: random.Random,
    *,
    records: int,
    shared_time: bool = False,
    text_length: int = 20_000,
    label_character: str = "~",
) -> IncidentEvidence:
    """Everything one location can return in one combined document.

    Network with the most device MACs, Protect with the most cameras, the
    unsupported Access source, the longest labels and the most assertions,
    every one mapped from the device. Labels and assertion identifiers repeat
    ``label_character``: a ``~`` is a token, a four-byte character four. This is the relay's largest timeline,
    and the worker reads at most as many sources per call.
    """
    location_id = worst_label(character=label_character)
    macs = worst_macs()
    cameras = worst_cameras()
    mappings = worst_mappings(macs[0], cameras, label_character)
    network = await network_document(
        rng,
        records=records,
        shared_time=shared_time,
        text_length=text_length,
        location_id=location_id,
        site=worst_label(character=label_character),
        mappings=mappings,
        device_macs=macs,
    )
    protect = await protect_document(
        rng,
        records_per_camera=records // len(cameras),
        cameras=cameras,
        shared_time=shared_time,
        location_id=location_id,
        mappings=mappings,
    )
    return combine_incident_evidence(
        [network, protect, unsupported_access_document(location_id=location_id, mappings=mappings)]
    )


def document_as_received(
    evidence: IncidentEvidence,
    *,
    labels: Mapping[str, str | None] | None = None,
    assertion_ids: Sequence[str] = (),
    failed_sources: int = 0,
) -> IncidentEvidence:
    """``evidence`` as a document from outside request validation could carry it.

    Every source, and its records' provenance, takes ``labels`` (``source_tool``
    or a scope field); one assertion naming no record is added per
    ``assertion_ids`` item; and ``failed_sources`` unanswered Access sources are
    added. Overall status and record mappings are derived again, so the result
    is a valid document.
    """
    labels = dict(labels or {})
    tool = {"source_tool": labels.pop("source_tool")} if "source_tool" in labels else {}

    def relabel(item: Any) -> Any:
        return item.model_copy(update={**tool, "scope": item.scope.model_copy(update=labels)})

    sources = [
        SourceEvidence(
            source=relabel(source),
            records=tuple(
                record.model_copy(update={"provenance": relabel(record.provenance)})
                for record in evidence.records
                if record.source_id == source.source_id
            ),
        )
        for source in evidence.sources
    ]
    for index in range(failed_sources):
        context = SourceContext(
            source_id=f"access.incident_evidence.{index:04d}",
            product=Product.ACCESS,
            api_family=None,
            scope=Scope(location_id="fixture-location"),
            query={},
            collected_at=format_utc(NOW),
            requested_window=evidence.requested_window,
        )
        sources.append(source_failed(context, SourceFailure(kind=FailureKind.UNSUPPORTED)))
    # Location identifiers: no record names one, so no record's mapping changes.
    extra = [
        MappingAssertion.model_validate(
            {
                "entity": {"kind": "location", "id_kind": "location_id", "id": identifier},
                "target": {"kind": "location", "id_kind": "location_id", "id": "fixture-location"},
                "source": "operator_input",
            }
        )
        for identifier in assertion_ids
    ]
    mappings = None if evidence.mappings is None and not extra else (*(evidence.mappings or ()), *extra)
    return assemble_incident_evidence(
        requested_window=evidence.requested_window, budgets=evidence.budgets, sources=sources, mappings=mappings
    )
