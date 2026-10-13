"""Node JSON.stringify reference vectors for evidence number identities."""

from __future__ import annotations

import json

import pytest
from unifi_core.incident_evidence import TimeWindow, _digest_json, _digest_number, evidence_digest, parse_event_time

# Captured from Node JSON.stringify and node:crypto SHA-256. The digest payload
# has sorted keys, attributes={value}, no identity/entities/type/summary, and
# time=["time", "integer", 1786190400000]. No Node process is needed by pytest.
NODE_VECTORS = [
    (1, "1", "034529c1d7cea72bebabde67"),
    (1.0, "1", "034529c1d7cea72bebabde67"),
    (0.1, "0.1", "21960c3774cb77d838c9cbf9"),
    (1e21, "1e+21", "fd9a0fb588e3f7c98c0b6c30"),
    (-0.0, "0", "85b54be939c1fe501ff839ab"),
    (9007199254740991, "9007199254740991", "20f9940a59fa9ed62853b4d5"),
    (9007199254740992, "9007199254740992", "573feb4b07f0b5c28ef6c369"),
    (9007199254740993, "9007199254740992", "573feb4b07f0b5c28ef6c369"),
    (2**68, "295147905179352830000", "a32560a9b16df3474abcee2a"),
    (1e-6, "0.000001", "482912932cbe61b60da691d7"),
    (1e-7, "1e-7", "3c32f55597bbd3a59357881f"),
    (333333333.33333329, "333333333.3333333", "f5819170f97baa6f261b9f23"),
    (5e-324, "5e-324", "e5198a90cd4e1f88888b2006"),
    (1.7976931348623157e308, "1.7976931348623157e+308", "394fd0a9c848ac37b8fdd2e2"),
]


@pytest.mark.parametrize("value,serialized,expected_digest", NODE_VECTORS)
def test_evidence_digest_matches_node(value: int | float, serialized: str, expected_digest: str) -> None:
    window = TimeWindow(start="2026-08-08T12:00:00.000000Z", end="2026-08-08T13:00:00.000000Z")
    time = parse_event_time("time", 1786190400000, window=window)
    assert _digest_number(value) == serialized
    assert (
        evidence_digest(
            source_record_id=None,
            source_record_id_field=None,
            time=time,
            event_type=None,
            summary=None,
            entities=[],
            attributes={"value": value},
        )
        == expected_digest
    )


def test_number_canonicalization_preserves_other_digest_encoding() -> None:
    value = {"\U0001f600": [True, False, None, "\x7f\u00e9"], "\uffff": "\n", "a": "1.0"}
    assert _digest_json(value) == json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert _digest_json({"nested": [1.0, -0.0, {"value": 1e-7}]}) == '{"nested":[1,0,{"value":1e-7}]}'


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), 10**400])
def test_unrepresentable_numbers_fail_without_echoing_evidence(value: int | float) -> None:
    with pytest.raises(ValueError, match="Evidence number"):
        _digest_number(value)
