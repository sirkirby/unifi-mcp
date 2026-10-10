"""Golden corpus, schema-artifact drift and fixture sanitization for incident evidence."""

from __future__ import annotations

import ipaddress
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest
from unifi_core.incident_evidence import (
    IncidentEvidence,
    canonical_json,
    evidence_to_json,
    incident_evidence_json_schema,
    validate_incident_evidence,
)

from .incident_evidence_corpus import CASES_DIR, SCHEMA_PATH, UPDATE_ENV, build_case, case_paths, load_case

UPDATING = os.environ.get(UPDATE_ENV) == "1"
REQUIRED_CASES = {
    "auth_failure_total",
    "budget_exhaustion",
    "duplicate_stable_ids",
    "healthy_empty",
    "malformed_timestamps",
    "mapping_outcomes",
    "network_protect_real_shapes",
    "out_of_window_boundaries",
    "pagination_cap_truncation",
    "partial_window_coverage",
    "timeouts",
    "timezone_precision_variants",
    "tool_response_envelopes",
    "unavailable_source",
    "unsupported_source",
}


def _dump(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def test_corpus_has_every_required_case() -> None:
    assert {path.stem for path in case_paths()} == REQUIRED_CASES


@pytest.mark.parametrize("path", case_paths(), ids=lambda p: p.stem)
def test_golden_case_matches_normalized_output(path: Path) -> None:
    case = load_case(path)
    produced = evidence_to_json(build_case(case["input"]))
    if UPDATING:
        case["expected"] = produced
        path.write_text(json.dumps(case, indent=2, ensure_ascii=True) + "\n")
    assert produced == case["expected"]


@pytest.mark.parametrize("path", case_paths(), ids=lambda p: p.stem)
def test_golden_expected_output_validates_and_is_canonical(path: Path) -> None:
    expected = load_case(path)["expected"]
    evidence = validate_incident_evidence(expected)
    assert json.loads(canonical_json(evidence)) == expected


def test_schema_artifact_has_not_drifted() -> None:
    generated = _dump(incident_evidence_json_schema())
    if UPDATING:
        SCHEMA_PATH.write_text(generated)
    assert SCHEMA_PATH.read_text() == generated, (
        f"incident evidence schema drifted; regenerate with {UPDATE_ENV}=1 and review the diff"
    )


def test_schema_artifact_is_versioned() -> None:
    schema = json.loads(SCHEMA_PATH.read_text())
    assert schema["$id"] == "urn:unifi-mcp:unifi-incident-evidence:v1"
    assert schema["properties"]["schema_version"]["const"] == 1
    assert schema["additionalProperties"] is False


def test_expected_outputs_validate_against_schema_artifact() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text())
    for path in case_paths():
        jsonschema.validate(load_case(path)["expected"], schema)


def test_contract_rejects_tampered_golden_output() -> None:
    expected = load_case(CASES_DIR / "auth_failure_total.json")["expected"]
    tampered = {**expected, "overall": "empty", "coverage_complete": True}
    with pytest.raises(ValueError):
        IncidentEvidence.model_validate(tampered)


# --- sanitization ---------------------------------------------------------

_MAC_TOKEN = re.compile(r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}(?![0-9A-Fa-f])")
_IPV4_TOKEN = re.compile(r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9.])")
_DOCUMENTATION_NETS = [ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")]
_NAME_KEYS = {"name", "hostname", "camera_name", "display_name", "ssid", "essid", "recognized_person_name"}


def _strings(value: Any, key: str | None = None):
    if isinstance(value, dict):
        for child_key, child in value.items():
            yield from _strings(child, child_key)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child, key)
    elif isinstance(value, str):
        yield key, value


@pytest.mark.parametrize("path", case_paths(), ids=lambda p: p.stem)
def test_fixture_contains_only_synthetic_identifiers(path: Path) -> None:
    for key, text in _strings(load_case(path)):
        for mac in _MAC_TOKEN.findall(text):
            first_octet = int(mac[:2], 16)
            assert first_octet & 0x02 and not first_octet & 0x01, f"{path.stem}: MAC {mac} is not locally administered"
        for ip in _IPV4_TOKEN.findall(text):
            address = ipaddress.ip_address(ip)
            assert any(address in net for net in _DOCUMENTATION_NETS), f"{path.stem}: {ip} is not a documentation IP"
        if key in _NAME_KEYS:
            assert text.startswith("fixture-") or _IPV4_TOKEN.fullmatch(text), f"{path.stem}: name {text!r}"
        assert "@" not in text, f"{path.stem}: e-mail-like value {text!r}"
