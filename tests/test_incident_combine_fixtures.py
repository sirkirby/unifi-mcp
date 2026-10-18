"""The combine fixtures the worker compares against are Core's own output."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from unifi_core.incident_collection import combine_incident_evidence
from unifi_core.incident_evidence import canonical_json

CORPUS = Path(__file__).resolve().parent / "fixtures/incident_evidence"


def test_combine_fixture_drift() -> None:
    subprocess.run([sys.executable, str(CORPUS / "generate_combine.py"), "--check"], check=True)


@pytest.mark.parametrize("path", sorted((CORPUS / "combine").glob("*.json")), ids=lambda p: p.stem)
def test_combine_corpus(path: Path) -> None:
    fixture = json.loads(path.read_text())
    if fixture.get("error"):
        with pytest.raises(ValueError, match="disagree about source"):
            combine_incident_evidence(fixture["inputs"])
    else:
        assert canonical_json(combine_incident_evidence(fixture["inputs"])) == canonical_json(fixture["expected"])
