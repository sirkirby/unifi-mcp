"""The relay consumes validated evidence; it never interprets product events."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from unifi_core.incident_collection import combine_incident_evidence
from unifi_core.incident_evidence import (
    SourceEvidence,
    assemble_incident_evidence,
    canonical_json,
    evidence_to_json,
    validate_incident_evidence,
)
from unifi_mcp_relay.location_timeline import (
    PRODUCT_TOOLS,
    TOOL_ANNOTATIONS,
    TOOL_INPUT_SCHEMA,
    handle_location_timeline,
)

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "tests/fixtures/incident_evidence"


def read(name="network_protect_real_shapes"):
    return json.loads((CORPUS / "cases" / f"{name}.json").read_text())["expected"]


def arguments(document):
    limits = document["budgets"]["limits"]
    return {
        "start": document["requested_window"]["start"],
        "end": document["requested_window"]["end"],
        "max_window_seconds": limits["window_seconds"],
        "max_events": limits["events"],
        "max_calls": limits["calls"],
        "max_elapsed_ms": limits["elapsed_ms"],
        "mappings": document["mappings"],
    }


def product_documents(document):
    doc = validate_incident_evidence(document)
    return {
        product: evidence_to_json(
            assemble_incident_evidence(
                requested_window=doc.requested_window,
                budgets=doc.budgets,
                mappings=doc.mappings,
                sources=[
                    SourceEvidence(source=s, records=tuple(r for r in doc.records if r.source_id == s.source_id))
                    for s in doc.sources
                    if s.product.value == product
                ],
            )
        )
        for product in sorted({s.product.value for s in doc.sources})
    }


@pytest.mark.parametrize("path", sorted((CORPUS / "cases").glob("*.json")), ids=lambda p: p.stem)
async def test_golden_documents_are_validated_and_combined(path):
    document = json.loads(path.read_text())["expected"]
    products = product_documents(document)

    async def forward(tool_name, arguments):
        product = next(p for p, tool in PRODUCT_TOOLS.items() if tool == tool_name)
        return {"success": True, "data": products[product]}

    # Access is a reserved contract product and intentionally has no consumer.
    if "access" in products:
        return
    result = await handle_location_timeline(
        {**arguments(document), "products": list(products)}, AsyncMock(forward=forward)
    )
    assert result["success"] is True
    assert canonical_json(result["data"]) == canonical_json(combine_incident_evidence(products.values()))


async def test_forwarded_arguments_match_actual_manifests():
    documents = product_documents(read())
    manifests = {}
    for product, tool in PRODUCT_TOOLS.items():
        path = ROOT / f"apps/{product}/src/unifi_{product}_mcp/tools_manifest.json"
        manifests[tool] = next(t for t in json.loads(path.read_text())["tools"] if t["name"] == tool)["schema"]

    async def forward(tool_name, arguments):
        schema = manifests[tool_name]
        assert set(arguments) == set(schema["properties"])
        assert set(schema["required"]) <= set(arguments)
        assert arguments["start"].endswith("Z")
        assert "start_time" not in arguments and "end_time" not in arguments
        product = next(p for p, tool in PRODUCT_TOOLS.items() if tool == tool_name)
        return {"success": True, "data": documents[product]}

    forwarder = AsyncMock()
    forwarder.forward.side_effect = forward
    result = await handle_location_timeline(
        {**arguments(read()), "device_macs": ["02:00:00:00:00:01"], "camera_ids": ["fixture-camera"]}, forwarder
    )
    assert result["success"] is True
    assert forwarder.forward.await_count == 2
    assert result["data"]["budgets"]["limits"]["calls"] == 20
    assert TOOL_INPUT_SCHEMA["required"] == ["start", "end"]
    assert TOOL_INPUT_SCHEMA["additionalProperties"] is False
    assert TOOL_ANNOTATIONS["readOnlyHint"] is True


@pytest.mark.parametrize(
    "response,outcome",
    [
        (None, "unsupported"),
        ({"success": False, "error": "fixture-private-text"}, "unavailable"),
        ({"success": True, "data": []}, "parse_failed"),
        ({"data": {}}, "parse_failed"),
    ],
)
async def test_missing_and_invalid_product_responses_are_explicit(response, outcome):
    result = await handle_location_timeline(
        {**arguments(read()), "products": ["network", "access"]}, AsyncMock(forward=AsyncMock(return_value=response))
    )
    doc = validate_incident_evidence(result["data"])
    assert doc.overall == "failed" and not doc.coverage_complete
    assert {s.product.value: s.outcome.value for s in doc.sources} == {"network": outcome, "access": "unsupported"}
    assert "fixture-private-text" not in json.dumps(result)


@pytest.mark.parametrize(
    "exc,outcome",
    [(TimeoutError(), "timeout"), (ConnectionError(), "unavailable"), (PermissionError(), "permission_denied")],
)
async def test_transport_failure_is_classified_without_exception_text(exc, outcome, caplog):
    exc.args = ("fixture-private-text",)
    result = await handle_location_timeline(
        {**arguments(read()), "products": ["network"]}, AsyncMock(forward=AsyncMock(side_effect=exc))
    )
    assert result["data"]["sources"][0]["outcome"] == outcome
    assert "fixture-private-text" not in json.dumps(result) + caplog.text


async def test_success_and_failure_are_both_retained():
    products = product_documents(read())

    async def forward(tool_name, arguments):
        if tool_name == PRODUCT_TOOLS["network"]:
            return {"success": True, "data": products["network"]}
        raise TimeoutError("fixture-private-text")

    result = await handle_location_timeline(arguments(read()), AsyncMock(forward=forward))
    doc = validate_incident_evidence(result["data"])
    assert doc.overall == "partial" and doc.records
    assert [s.outcome.value for s in doc.sources] == ["complete", "timeout"]


@pytest.mark.parametrize("path", sorted((CORPUS / "invalid").glob("*.json")), ids=lambda p: p.stem)
async def test_invalid_corpus_is_never_trusted(path):
    bad = json.loads(path.read_text())["evidence"]
    result = await handle_location_timeline(
        {**arguments(read()), "products": ["network"]},
        AsyncMock(forward=AsyncMock(return_value={"success": True, "data": bad})),
    )
    assert result["success"] is True
    assert result["data"]["overall"] == "failed"
    assert result["data"]["sources"][0]["outcome"] == "parse_failed"
    assert result["data"]["records"] == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("start", "2026-08-08T12:00:00"),
        ("end", "bad"),
        ("max_calls", 0),
        ("device_macs", ["fixture-name"]),
        ("camera_ids", [" camera "]),
        ("products", []),
        ("products", ["network", "network"]),
        ("products", ["unknown"]),
        ("area_hint", "front"),
        ("start_time", "old-input"),
        ("mappings", [{"entity": {}, "target": {}, "source": "guessed"}]),
    ],
)
async def test_invalid_arguments_never_read(field, value):
    forwarder = AsyncMock()
    result = await handle_location_timeline({**arguments(read()), field: value}, forwarder)
    assert result["success"] is False
    forwarder.forward.assert_not_awaited()


async def test_valid_but_unrelated_document_is_parse_failed():
    wrong = copy.deepcopy(product_documents(read())["network"])
    wrong["budgets"]["limits"]["calls"] += 1
    result = await handle_location_timeline(
        {**arguments(read()), "products": ["network"]},
        AsyncMock(forward=AsyncMock(return_value={"success": True, "data": wrong})),
    )
    assert result["data"]["sources"][0]["outcome"] == "parse_failed"


async def test_window_budget_is_reported_even_without_product():
    args = {**arguments(read()), "max_window_seconds": 1, "products": ["access"]}
    result = await handle_location_timeline(args, AsyncMock())
    assert result["data"]["budgets"]["exhausted"] == ["window"]
    validate_incident_evidence(result["data"])


def test_combine_fixture_drift():
    subprocess.run([sys.executable, str(CORPUS / "generate_combine.py"), "--check"], check=True)


@pytest.mark.parametrize("path", sorted((CORPUS / "combine").glob("*.json")), ids=lambda p: p.stem)
def test_combine_corpus(path):
    fixture = json.loads(path.read_text())
    if fixture.get("error"):
        with pytest.raises(ValueError, match="disagree about source"):
            combine_incident_evidence(fixture["inputs"])
    else:
        assert canonical_json(combine_incident_evidence(fixture["inputs"])) == canonical_json(fixture["expected"])
