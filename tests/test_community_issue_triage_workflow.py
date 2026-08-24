from __future__ import annotations

import json
import os
import re
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "community-issue-triage.md"


LOCK = ROOT / ".github" / "workflows" / "community-issue-triage.lock.yml"


def _validator_script(output_path: Path) -> str:
    source = WORKFLOW.read_text()
    match = re.search(r"node <<'NODE'\n(?P<script>.*?)\n        NODE", source, re.DOTALL)
    assert match is not None, "workflow validator heredoc was not found"
    script = textwrap.dedent(match.group("script"))
    script = script.replace(
        'const outputPath = "/tmp/gh-aw/agent_output.json";',
        f"const outputPath = {json.dumps(str(output_path))};",
    )
    return script


def _run_validator(tmp_path: Path, output: dict[str, object]):
    output_path = tmp_path / "agent_output.json"
    summary_path = tmp_path / "summary.md"
    output_path.write_text(json.dumps(output))

    env = os.environ.copy()
    env.update(
        {
            "GITHUB_STEP_SUMMARY": str(summary_path),
            "TARGET_NUMBER": "521",
        }
    )
    return subprocess.run(
        ["node", "-e", _validator_script(output_path)],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )


def _triage_reviewed_output() -> dict[str, object]:
    return {
        "items": [
            {
                "type": "add_labels",
                "labels": [
                    {
                        "name": "triage-reviewed",
                        "rationale": "The required normal triage pass completed.",
                        "confidence": "HIGH",
                    }
                ],
            }
        ]
    }


def _allowed_label_output() -> dict[str, object]:
    return {
        "items": [
            {
                "type": "add_labels",
                "labels": [
                    {
                        "name": "bug",
                        "rationale": "The report describes reproducible incorrect behavior.",
                        "confidence": "HIGH",
                    }
                ],
            }
        ]
    }


def _compiled_safe_output_config(compiled: str) -> dict[str, object]:
    line = next(line for line in compiled.splitlines() if "GH_AW_SAFE_OUTPUTS_CONFIG:" in line)
    encoded = line.split("GH_AW_SAFE_OUTPUTS_CONFIG: ", 1)[1]
    return json.loads(json.loads(encoded))


def test_triage_reviewed_is_rejected_as_human_only(tmp_path: Path):
    result = _run_validator(tmp_path, _triage_reviewed_output())

    assert result.returncode == 1
    assert "label outside allowlist" in result.stderr


def test_noop_output_still_passes_validation(tmp_path: Path):
    output = {"items": [{"type": "noop", "message": "No public action is warranted."}]}
    result = _run_validator(tmp_path, output)

    assert result.returncode == 0, result.stderr


def test_allowed_label_passes_and_receives_trusted_target(tmp_path: Path):
    result = _run_validator(tmp_path, _allowed_label_output())

    assert result.returncode == 0, result.stderr
    trusted_output = json.loads((tmp_path / "agent_output.json").read_text())
    assert trusted_output["items"][0]["item_number"] == 521
    summary = (tmp_path / "summary.md").read_text()
    assert "The report describes reproducible incorrect behavior." in summary


def test_source_and_compiled_output_policy_keep_triage_reviewed_human_only():
    source = WORKFLOW.read_text()
    compiled = LOCK.read_text()
    policy = "Never propose `triage-reviewed`. That completion label is reserved for a human"

    assert policy in source
    config = _compiled_safe_output_config(compiled)
    assert "triage-reviewed" not in config["add_labels"]["allowed"]
    assert "triage-reviewed" in config["add_labels"]["blocked"]


def test_scoped_issue_search_contract_is_in_source_and_compiled_manifest():
    source = WORKFLOW.read_text()
    compiled_lines = LOCK.read_text().splitlines()
    manifest_line = next(line for line in compiled_lines if line.startswith("# gh-aw-manifest: "))
    manifest = json.loads(manifest_line.removeprefix("# gh-aw-manifest: "))
    github_server = next(server for server in manifest["mcp_servers"] if server["name"] == "github")

    assert ("Call `search_issues` with `owner: sirkirby`, `repo: unifi-mcp`, and a nonempty query") in source.replace(
        "\n", " "
    )
    assert "search_issues" in github_server["tools"]
