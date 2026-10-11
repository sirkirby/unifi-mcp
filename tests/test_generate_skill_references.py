"""The skill reference check fails when a tool category has no marker section."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_script_path = Path(__file__).parent.parent / "scripts" / "generate_skill_references.py"
_spec = importlib.util.spec_from_file_location("generate_skill_references", _script_path)
generator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(generator)


def _server(tmp_path: Path, reference: str) -> dict:
    manifest = {
        "count": 2,
        "module_map": {"demo_list_things": "demo.tools.things", "demo_get_widget": "demo.tools.widgets"},
        "tools": [
            {"name": "demo_list_things", "description": "List things.", "annotations": {"readOnlyHint": True}},
            {"name": "demo_get_widget", "description": "Get a widget.", "annotations": {"readOnlyHint": True}},
        ],
    }
    manifest_path = tmp_path / "tools_manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    reference_path = tmp_path / "demo-tools.md"
    reference_path.write_text(reference)
    return {"name": "demo", "manifest": manifest_path, "reference": reference_path, "module_strip": "demo.tools."}


def _section(category: str) -> str:
    return f"<!-- AUTO:tools:{category} -->\n<!-- /AUTO:tools:{category} -->\n"


@pytest.mark.parametrize(("sections", "expected"), [(["things"], 1), (["things", "widgets"], 0)])
def test_check_fails_when_a_category_has_no_marker_section(tmp_path, monkeypatch, sections, expected) -> None:
    server = _server(tmp_path, "# Demo Server Tool Reference (2 tools)\n\n" + "".join(map(_section, sections)))
    monkeypatch.setattr(generator, "SERVERS", [server])
    monkeypatch.setattr(sys, "argv", ["generate_skill_references.py"])
    assert generator.main() == 0  # generating fills what it can and never fails on a missing section
    monkeypatch.setattr(sys, "argv", ["generate_skill_references.py", "--check"])
    assert generator.main() == expected
