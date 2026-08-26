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

REQUIRED_LABELS = ["needs-info"]
FORMER_CLASSIFICATION_LABELS = [
    "bug",
    "enhancement",
    "documentation",
    "dependencies",
    "docker",
    "github-actions",
    "api",
    "network",
    "protect",
    "access",
]

NO_CANDIDATE_UNCERTAINTY = (
    "Lexical result: No candidate met the deterministic threshold; duplicate status remains unknown."
)
TEST_SHA = "1" * 40


def _canonical_comment(proposal: dict[str, object]) -> str:
    return json.dumps(proposal, separators=(",", ":"), ensure_ascii=False)


def _missing_information_comment(*fields: str) -> str:
    return _canonical_comment({"version": 1, "kind": "missing_information", "fields": list(fields)})


def _repository_evidence_comment(path: str, quote: str) -> str:
    return _canonical_comment({"version": 1, "kind": "repository_evidence", "path": path, "quote": quote})


def _trusted_context(target_number: int = 521) -> dict[str, object]:
    return {
        "version": 1,
        "status": "complete",
        "strategy": "bounded-title-lexical-v1",
        "target": {"number": target_number},
        "search_performed": True,
        "candidates": [],
        "scanned": 560,
        "truncated": False,
    }


def _trusted_context_with_candidate(target_number: int = 521) -> dict[str, object]:
    context = _trusted_context(target_number)
    context["candidates"] = [{"number": 225, "state": "closed", "score": 19}]
    return context


def _validator_script(output_path: Path, repository_files: dict[str, str]) -> str:
    source = WORKFLOW.read_text()
    match = re.search(r"node <<'NODE'\n(?P<script>.*?)\n        NODE", source, re.DOTALL)
    assert match is not None, "workflow validator heredoc was not found"
    script = textwrap.dedent(match.group("script"))
    script = script.replace(
        'const outputPath = "/tmp/gh-aw/agent_output.json";',
        f"const outputPath = {json.dumps(str(output_path))};",
    )
    fetch_stub = f"""
const testRepositoryFiles = {json.dumps(repository_files)};
globalThis.fetch = async (rawUrl, options) => {{
  const url = new URL(rawUrl);
  const prefix = "/repos/sirkirby/unifi-mcp/contents/";
  const encodedPath = url.pathname.startsWith(prefix) ? url.pathname.slice(prefix.length) : "";
  const path = encodedPath.split("/").map(decodeURIComponent).join("/");
  const authorized = options?.headers?.Authorization === "Bearer test-token";
  const validRequest =
    url.protocol === "https:" &&
    url.hostname === "api.github.com" &&
    url.searchParams.get("ref") === {json.dumps(TEST_SHA)} &&
    authorized;
  const found = validRequest && Object.prototype.hasOwnProperty.call(testRepositoryFiles, path);
  return {{
    ok: found,
    status: found ? 200 : 404,
    text: async () => found ? testRepositoryFiles[path] : "",
  }};
}};
"""
    return fetch_stub + script


def _run_validator(
    tmp_path: Path,
    output: dict[str, object],
    *,
    duplicate_context: dict[str, object] | str | None = None,
    target_number: int = 521,
    repository_files: dict[str, str] | None = None,
):
    output_path = tmp_path / "agent_output.json"
    summary_path = tmp_path / "summary.md"
    output_path.write_text(json.dumps(output))

    env = os.environ.copy()
    env.update(
        {
            "GITHUB_STEP_SUMMARY": str(summary_path),
            "GITHUB_SHA": TEST_SHA,
            "GITHUB_TOKEN": "test-token",
            "TARGET_NUMBER": str(target_number),
            "TRUSTED_DUPLICATE_CONTEXT": (
                json.dumps(_trusted_context())
                if duplicate_context is None
                else (duplicate_context if isinstance(duplicate_context, str) else json.dumps(duplicate_context))
            ),
        }
    )
    return subprocess.run(
        ["node", "-e", _validator_script(output_path, repository_files or {})],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )


def _research_script() -> str:
    source = WORKFLOW.read_text()
    match = re.search(
        r"        id: research\n.*?          script: \|\n(?P<script>.*?)\n\n  activation:",
        source,
        re.DOTALL,
    )
    assert match is not None, "trusted duplicate research script was not found"
    return textwrap.dedent(match.group("script"))


def _run_research(
    *,
    target: dict[str, object],
    candidates: list[dict[str, object]],
    candidate_pages: list[list[dict[str, object]]] | None = None,
    graphql_error: bool = False,
):
    graphql_implementation = (
        'async () => { throw new Error("simulated GraphQL failure"); }'
        if graphql_error
        else "async () => { const nodes = candidatePages[graphqlCalls] || []; "
        "graphqlCalls += 1; return {repository: {issues: {nodes, pageInfo: {"
        "hasNextPage: graphqlCalls < candidatePages.length, "
        "endCursor: graphqlCalls < candidatePages.length ? String(graphqlCalls) : null"
        "}}}}; }"
    )
    pages = candidate_pages if candidate_pages is not None else [candidates]
    harness = f"""
const fixture = JSON.parse(require("fs").readFileSync(0, "utf8"));
const target = fixture.target;
const candidatePages = fixture.candidatePages;
let graphqlCalls = 0;
const outputs = {{}};
const core = {{
  setFailed: (message) => {{ throw new Error(message); }},
  setOutput: (name, value) => {{ outputs[name] = value; }},
}};
const context = {{repo: {{owner: "sirkirby", repo: "unifi-mcp"}}}};
const github = {{
  rest: {{issues: {{
    get: async () => ({{data: target}}),
    listLabelsForRepo: async () => ({{data: []}}),
  }}}},
  paginate: async () => {json.dumps([{"name": label} for label in REQUIRED_LABELS])},
  graphql: {graphql_implementation},
}};
process.env.TARGET_NUMBER = "228";
process.env.RETENTION_VERIFIED = "true";
(async () => {{
{textwrap.indent(_research_script(), "  ")}
}})().then(() => process.stdout.write(JSON.stringify(outputs)));
"""
    return subprocess.run(
        ["node", "-e", harness],
        capture_output=True,
        check=False,
        input=json.dumps({"target": target, "candidatePages": pages}),
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
                        "name": "needs-info",
                        "rationale": "The report is missing one objectively required diagnostic detail.",
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
    output = {
        "items": [
            {
                "type": "noop",
                "message": "No public action is warranted.\n" + NO_CANDIDATE_UNCERTAINTY,
            }
        ]
    }
    result = _run_validator(tmp_path, output)

    assert result.returncode == 0, result.stderr


def test_validator_rejects_live_mixed_label_and_noop_shape(tmp_path: Path):
    output = _allowed_label_output()
    output["items"].append(
        {
            "type": "noop",
            "message": "The issue is ready for maintainer review.\n" + NO_CANDIDATE_UNCERTAINTY,
        }
    )

    result = _run_validator(tmp_path, output)

    assert result.returncode == 1
    assert "noop must be exclusive" in result.stderr


def test_validator_accepts_stage_a5_label_suggestion_and_staged_comment(tmp_path: Path):
    output = {
        "items": [
            {
                "type": "add_labels",
                "labels": [
                    {
                        "name": "needs-info",
                        "rationale": "The report is missing the controller version needed to reproduce the failure.",
                        "confidence": "HIGH",
                    },
                ],
            },
            {
                "type": "add_comment",
                "body": _missing_information_comment("controller_version"),
                "temporary_id": "aw_09GWN1A0",
            },
        ],
        "errors": [],
    }

    result = _run_validator(
        tmp_path,
        output,
        duplicate_context=_trusted_context(target_number=546),
        target_number=546,
    )

    assert result.returncode == 0, result.stderr
    trusted_output = json.loads((tmp_path / "agent_output.json").read_text())
    assert trusted_output["items"][0]["item_number"] == 546
    assert trusted_output["items"][0]["labels"][0]["suggest"] is True
    assert trusted_output["items"][1]["temporary_id"] == "aw_09GWN1A0"
    assert "The UniFi application family and version." in trusted_output["items"][1]["body"]
    assert NO_CANDIDATE_UNCERTAINTY in trusted_output["items"][1]["body"]
    assert "automated first-pass triage" in trusted_output["items"][1]["body"]

    del output["items"][1]["temporary_id"]
    without_framework_metadata = _run_validator(
        tmp_path,
        output,
        duplicate_context=_trusted_context(target_number=546),
        target_number=546,
    )
    assert without_framework_metadata.returncode == 0, without_framework_metadata.stderr


def test_validator_renders_missing_information_from_closed_field_ids(tmp_path: Path):
    output = {
        "items": [
            {
                "type": "add_comment",
                "body": _missing_information_comment("package_version", "transport", "sanitized_error"),
            }
        ]
    }

    result = _run_validator(tmp_path, output)

    assert result.returncode == 0, result.stderr
    rendered = json.loads((tmp_path / "agent_output.json").read_text())["items"][0]["body"]
    assert rendered.startswith("To make this report actionable, please provide:")
    assert "The exact unifi-mcp package version or commit." in rendered
    assert "The transport in use: stdio, SSE, or streamable HTTP." in rendered
    assert "The complete sanitized error message or response status." in rendered
    assert NO_CANDIDATE_UNCERTAINTY in rendered
    assert rendered.endswith("This is an automated first-pass triage; a maintainer will make final decisions.")


def test_validator_verifies_repository_evidence_at_immutable_sha_and_renders_link(
    tmp_path: Path,
):
    quote = (
        "Read-only mode prevents mutation tools from changing controller state.\n"
        "Use confirm mode when you want preview-before-execution behavior."
    )
    repository_content = (
        "# Permissions\n\n"
        "The permission model has two independent controls.\n" + quote + "\n\nAdditional guidance follows.\n"
    )
    output = {
        "items": [
            {
                "type": "add_comment",
                "body": _repository_evidence_comment("docs/permissions.md", quote),
            }
        ]
    }

    result = _run_validator(
        tmp_path,
        output,
        repository_files={"docs/permissions.md": repository_content},
    )

    assert result.returncode == 0, result.stderr
    rendered = json.loads((tmp_path / "agent_output.json").read_text())["items"][0]["body"]
    assert "> Read-only mode prevents mutation tools" in rendered
    assert f"https://github.com/sirkirby/unifi-mcp/blob/{TEST_SHA}/docs/permissions.md#L4-L5" in rendered
    assert NO_CANDIDATE_UNCERTAINTY in rendered
    summary = (tmp_path / "summary.md").read_text()
    assert "The repository documentation currently states:" in summary
    assert "&gt; Read-only mode prevents mutation tools" in summary
    assert f"/blob/{TEST_SHA}/docs/permissions.md#L4-L5" in summary


def test_validator_rejects_free_form_581_style_comment(tmp_path: Path):
    output = {
        "items": [
            {
                "type": "add_comment",
                "body": (
                    "The permissions question is ready for maintainer review. Please find "
                    "and share the relevant repository documentation."
                ),
            }
        ]
    }

    result = _run_validator(tmp_path, output)

    assert result.returncode == 1
    assert "add_comment body must be canonical JSON" in result.stderr


def test_validator_rejects_noncanonical_or_agent_authored_comment_proposals(tmp_path: Path):
    proposals = (
        json.dumps({"version": 1, "kind": "missing_information", "fields": ["transport"]}),
        _canonical_comment(
            {
                "kind": "missing_information",
                "version": 1,
                "fields": ["transport"],
            }
        ),
        _canonical_comment(
            {
                "version": 1,
                "kind": "missing_information",
                "fields": ["transport"],
                "question": "Which transport are you using?",
            }
        ),
        _canonical_comment({"version": 2, "kind": "missing_information", "fields": ["transport"]}),
        _canonical_comment({"version": 1, "kind": "free_form", "body": "Please provide details."}),
    )
    for body in proposals:
        result = _run_validator(tmp_path, {"items": [{"type": "add_comment", "body": body}]})

        assert result.returncode == 1


def test_validator_rejects_invalid_missing_information_field_sets(tmp_path: Path):
    invalid_fields: tuple[object, ...] = (
        [],
        ["unknown_field"],
        ["transport", "transport"],
        ["package_version", "transport", "controller_version", "sanitized_error"],
        "transport",
        ["transport", 7],
    )
    for fields in invalid_fields:
        proposal = {"version": 1, "kind": "missing_information", "fields": fields}
        result = _run_validator(
            tmp_path,
            {"items": [{"type": "add_comment", "body": _canonical_comment(proposal)}]},
        )

        assert result.returncode == 1
        assert "missing_information requires 1 to 3 unique allowlisted field IDs" in result.stderr


def test_validator_rejects_untrusted_repository_evidence_selectors(tmp_path: Path):
    quote = "This exact repository guidance is long enough for validation."
    invalid_paths = (
        "../README.md",
        "/README.md",
        ".github/workflows/triage.md",
        "src/permissions.py",
        "docs/../README.md",
        "docs//permissions.md",
        "https://github.com/sirkirby/unifi-mcp/README.md",
    )
    for path in invalid_paths:
        result = _run_validator(
            tmp_path,
            {"items": [{"type": "add_comment", "body": _repository_evidence_comment(path, quote)}]},
        )

        assert result.returncode == 1
        assert "repository evidence path is outside the Markdown allowlist" in result.stderr

    for extra_key, value in (
        ("repo", "sirkirby/unifi-mcp"),
        ("ref", "main"),
        ("url", "https://github.com/sirkirby/unifi-mcp"),
        ("line", 10),
    ):
        proposal = {
            "version": 1,
            "kind": "repository_evidence",
            "path": "docs/permissions.md",
            "quote": quote,
            extra_key: value,
        }
        result = _run_validator(
            tmp_path,
            {"items": [{"type": "add_comment", "body": _canonical_comment(proposal)}]},
        )

        assert result.returncode == 1
        assert "repository_evidence proposal contains unexpected fields" in result.stderr


def test_validator_rejects_invalid_or_unverifiable_repository_quotes(tmp_path: Path):
    valid_path = "docs/permissions.md"
    invalid_quotes = (
        "short",
        " leading whitespace makes this quote noncanonical",
        "trailing whitespace makes this quote noncanonical ",
        "one\ntwo\nthree\nfour\nfive\nsix\nseven",
        "A tab\tinside repository evidence is not safe.",
        "A C1 next-line\u0085separator is not safe repository evidence.",
        "A Unicode line\u2028separator is not safe repository evidence.",
        "A Unicode paragraph\u2029separator is not safe repository evidence.",
        "x" * 601,
    )
    for quote in invalid_quotes:
        result = _run_validator(
            tmp_path,
            {"items": [{"type": "add_comment", "body": _repository_evidence_comment(valid_path, quote)}]},
        )

        assert result.returncode == 1
        assert "repository evidence quote must be" in result.stderr

    missing_quote = "This otherwise valid quote does not occur in the repository file."
    missing = _run_validator(
        tmp_path,
        {"items": [{"type": "add_comment", "body": _repository_evidence_comment(valid_path, missing_quote)}]},
        repository_files={valid_path: "Different repository documentation text."},
    )
    assert missing.returncode == 1
    assert "one unique contiguous match" in missing.stderr

    duplicate_quote = "This exact guidance appears more than once in the documentation."
    duplicate = _run_validator(
        tmp_path,
        {"items": [{"type": "add_comment", "body": _repository_evidence_comment(valid_path, duplicate_quote)}]},
        repository_files={valid_path: duplicate_quote + "\n" + duplicate_quote},
    )
    assert duplicate.returncode == 1
    assert "one unique contiguous match" in duplicate.stderr

    repeated_line = "Repeated repository guidance line."
    overlapping_quote = "\n".join([repeated_line] * 6)
    overlapping = _run_validator(
        tmp_path,
        {
            "items": [
                {
                    "type": "add_comment",
                    "body": _repository_evidence_comment(valid_path, overlapping_quote),
                }
            ]
        },
        repository_files={valid_path: "\n".join([repeated_line] * 7)},
    )
    assert overlapping.returncode == 1
    assert "one unique contiguous match" in overlapping.stderr


def test_validator_rejects_secret_like_verified_repository_quote(tmp_path: Path):
    quote = "The example token=abcdefghijklmnop123456 must never be published."
    output = {"items": [{"type": "add_comment", "body": _repository_evidence_comment("docs/security.md", quote)}]}

    result = _run_validator(
        tmp_path,
        output,
        repository_files={"docs/security.md": quote},
    )

    assert result.returncode == 1
    assert "secret-like content" in result.stderr


def test_validator_rejects_invalid_or_misplaced_temporary_id(tmp_path: Path):
    invalid_comment_ids: tuple[object, ...] = (
        "aw_x",
        "aw_0123456789abc",
        "aw_bad-value",
        " aw_09GWN1A0",
        "aw_09GWN1A0 ",
        "aw_09GWN1A0\n",
        "aw_０9GWN1A0",
        "temporary_123",
        123,
    )
    for temporary_id in invalid_comment_ids:
        output = {
            "items": [
                {
                    "type": "add_comment",
                    "body": _missing_information_comment("controller_version"),
                    "temporary_id": temporary_id,
                }
            ]
        }

        result = _run_validator(tmp_path, output)

        assert result.returncode == 1
        assert "invalid framework temporary_id" in result.stderr

    for output in (
        {
            "items": [
                {
                    "type": "noop",
                    "message": "No action is warranted.\n" + NO_CANDIDATE_UNCERTAINTY,
                    "temporary_id": "aw_09GWN1A0",
                }
            ]
        },
        {
            "items": [
                {
                    "type": "add_labels",
                    "labels": _allowed_label_output()["items"][0]["labels"],
                    "temporary_id": "aw_09GWN1A0",
                }
            ]
        },
    ):
        result = _run_validator(tmp_path, output)

        assert result.returncode == 1
        assert "unexpected fields" in result.stderr

    forbidden_fields: dict[str, object] = {
        "item_number": 546,
        "repo": "sirkirby/unifi-mcp",
        "target": "status",
        "comment_id": 123,
        "reply_to_id": "aw_parent",
        "suggest": True,
        "secrecy": "public",
        "integrity": "approved",
    }
    for field, value in forbidden_fields.items():
        output = {
            "items": [
                {
                    "type": "add_comment",
                    "body": _missing_information_comment("controller_version"),
                    "temporary_id": "aw_09GWN1A0",
                    field: value,
                }
            ]
        }

        result = _run_validator(tmp_path, output)

        assert result.returncode == 1


def test_temporary_id_pattern_matches_pinned_compiled_contract():
    pattern = "^#?aw_[A-Za-z0-9_]{3,12}$"

    assert pattern in WORKFLOW.read_text()
    assert f'"pattern": "{pattern}"' in LOCK.read_text()


def test_allowed_label_passes_and_receives_trusted_target(tmp_path: Path):
    result = _run_validator(tmp_path, _allowed_label_output())

    assert result.returncode == 0, result.stderr
    trusted_output = json.loads((tmp_path / "agent_output.json").read_text())
    assert trusted_output["items"][0]["item_number"] == 521
    assert trusted_output["items"][0]["labels"] == [
        {
            "name": "needs-info",
            "rationale": "The report is missing one objectively required diagnostic detail.",
            "confidence": "HIGH",
            "suggest": True,
        }
    ]
    summary = (tmp_path / "summary.md").read_text()
    assert "The report is missing one objectively required diagnostic detail." in summary
    assert NO_CANDIDATE_UNCERTAINTY in summary
    assert "If safe-output processing succeeds" in summary
    assert "comments remain preview-only" in summary


def test_validator_rejects_agent_control_of_issue_intent_suggestion(tmp_path: Path):
    output = _allowed_label_output()
    output["items"][0]["labels"][0]["suggest"] = True

    result = _run_validator(tmp_path, output)

    assert result.returncode == 1
    assert "label intent contains unexpected fields" in result.stderr


def test_validator_rejects_every_former_classification_label(tmp_path: Path):
    for label_name in FORMER_CLASSIFICATION_LABELS:
        output = _allowed_label_output()
        output["items"][0]["labels"][0]["name"] = label_name

        result = _run_validator(tmp_path, output)

        assert result.returncode == 1
        assert "label outside allowlist" in result.stderr


def test_validator_rejects_historical_multi_label_output_in_narrow_canary(tmp_path: Path):
    output = {
        "items": [
            {
                "type": "add_labels",
                "labels": [
                    {
                        "name": "enhancement",
                        "rationale": (
                            "Issue proposes new functionality: enriching DPI traffic-flow statistics "
                            "with resolved application and category names from the UniFi Integration API."
                        ),
                        "confidence": "HIGH",
                    },
                    {
                        "name": "network",
                        "rationale": (
                            "Issue explicitly targets the network component — specifically the "
                            "unifi_get_traffic_flow_statistics tool and DPI application catalogue."
                        ),
                        "confidence": "HIGH",
                    },
                ],
            }
        ],
        "errors": [],
    }

    result = _run_validator(
        tmp_path,
        output,
        duplicate_context=_trusted_context(target_number=546),
        target_number=546,
    )

    assert result.returncode == 1
    assert "add_labels requires exactly one needs-info label" in result.stderr


def test_validator_rejects_missing_malformed_or_mismatched_duplicate_context(tmp_path: Path):
    output = {"items": [{"type": "noop", "message": "No public action is warranted."}]}

    malformed = _run_validator(tmp_path, output, duplicate_context="not-json")
    assert malformed.returncode == 1
    assert "malformed trusted duplicate context" in malformed.stderr

    mismatched = _trusted_context(target_number=522)
    mismatch = _run_validator(tmp_path, output, duplicate_context=mismatched)
    assert mismatch.returncode == 1
    assert "invalid trusted duplicate context" in mismatch.stderr

    missing_skip_reason = _trusted_context()
    missing_skip_reason["search_performed"] = False
    missing_reason = _run_validator(tmp_path, output, duplicate_context=missing_skip_reason)
    assert missing_reason.returncode == 1
    assert "invalid trusted duplicate context" in missing_reason.stderr


def test_validator_rejects_unexpected_candidate_fields(tmp_path: Path):
    context = _trusted_context_with_candidate()
    context["candidates"] = [
        {
            "number": 225,
            "state": "closed",
            "score": 12,
            "shared_terms": ["candidate", "<script>"],
        }
    ]
    output = {"items": [{"type": "noop", "message": "No public action is warranted."}]}

    result = _run_validator(tmp_path, output, duplicate_context=context)

    assert result.returncode == 1
    assert "invalid trusted duplicate context" in result.stderr


def test_validator_requires_top_candidate_acknowledgement(tmp_path: Path):
    generic = {"items": [{"type": "noop", "message": "No public action is warranted."}]}
    context = _trusted_context_with_candidate()

    missing = _run_validator(tmp_path, generic, duplicate_context=context)
    assert missing.returncode == 1
    assert "highest-ranked trusted candidate requires one structured assessment" in missing.stderr

    acknowledged = {
        "items": [
            {
                "type": "noop",
                "message": ("Candidate #225: RELATED — It reports the same malformed uvx argument failure."),
            }
        ]
    }
    accepted = _run_validator(tmp_path, acknowledged, duplicate_context=context)
    assert accepted.returncode == 0, accepted.stderr


def test_validator_accepts_exact_second_live_issue_228_output(tmp_path: Path):
    context = _trusted_context_with_candidate(target_number=228)
    output = {
        "items": [
            {
                "type": "noop",
                "message": (
                    'Issue 228 is closed and already carries the correct "bug" label; '
                    "no further labels or comment needed. Candidate #225: RELATED — both "
                    'report the identical malformed uvx args["--python-preference==0.16.0"] '
                    "manifest bug, resolved via a prior merged change."
                ),
            }
        ],
        "errors": [],
    }

    result = _run_validator(
        tmp_path,
        output,
        duplicate_context=context,
        target_number=228,
    )

    assert result.returncode == 0, result.stderr


def test_validator_requires_uppercase_verdict_and_substantive_candidate_reason(tmp_path: Path):
    context = _trusted_context_with_candidate()
    outputs = (
        (
            "Candidate #225: related — It reports the same malformed uvx argument failure.",
            "candidate assessment must match the required literal grammar",
        ),
        (
            "Candidate #225: RELATED —                     ",
            "candidate assessment reason must contain at least 20 visible characters",
        ),
        (
            "Candidate #225: RELATED — " + ("\u200b" * 20),
            "candidate assessment must match the required literal grammar",
        ),
        (
            "Candidate #225: RELATED — a" + ("\u034f" * 19),
            "candidate assessment reason must contain at least 20 visible characters",
        ),
        (
            "Candidate #225: RELATED — a" + ("\ufe0f" * 19),
            "candidate assessment reason must contain at least 20 visible characters",
        ),
        (
            "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\n"
            "Candidate #225: related — This contradictory assessment must be rejected.",
            "candidate assessment must match the required literal grammar",
        ),
        (
            "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\n"
            "Candidate #225: DUPLICATE — This unsupported verdict must be rejected.",
            "candidate assessment must match the required literal grammar",
        ),
        (
            "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\n"
            "Candidate#225: NOT_RELATED — This compact contradictory assessment must be rejected.",
            "candidate assessment must match the required literal grammar",
        ),
        (
            "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\n"
            "Candidate # 225: NOT_RELATED — This spaced contradictory assessment must be rejected.",
            "candidate assessment must match the required literal grammar",
        ),
        (
            "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\n"
            " Candidate #225: related — This indented assessment must be rejected.",
            "candidate assessment must match the required literal grammar",
        ),
        (
            "Additional rationale without sentence punctuation Candidate #225: RELATED — "
            "It reports the same malformed uvx argument failure.",
            "candidate assessment must match the required literal grammar",
        ),
        (
            "Additional rationale.\tCandidate #225: RELATED — It reports the same malformed uvx argument failure.",
            "candidate assessment must match the required literal grammar",
        ),
        (
            "Additional rationale.\vCandidate #225: RELATED — It reports the same malformed uvx argument failure.",
            "candidate assessment must match the required literal grammar",
        ),
        (
            "Additional rationale.\fCandidate #225: RELATED — It reports the same malformed uvx argument failure.",
            "candidate assessment must match the required literal grammar",
        ),
        (
            "Additional rationale.\ufeffCandidate #225: RELATED — It reports the same malformed uvx argument failure.",
            "candidate assessment must match the required literal grammar",
        ),
        (
            "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\n"
            "- Candidate #225: DUPLICATE — This bulleted assessment must be rejected.",
            "candidate assessment must match the required literal grammar",
        ),
        (
            "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\u2028"
            "Candidate #225: related — This Unicode-separated assessment must be rejected.",
            "candidate assessment must match the required literal grammar",
        ),
        (
            "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\u0085"
            "Candidate #225: NOT_RELATED — This next-line assessment must be rejected.",
            "candidate assessment line must contain exactly one assessment",
        ),
        (
            "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\f"
            "Candidate #225: NOT_RELATED — This form-feed assessment must be rejected.",
            "candidate assessment line must contain exactly one assessment",
        ),
        (
            "Candidate #225: RELATED — This has a sufficiently long reason. "
            "Candidate #225: NOT_RELATED — This same-line contradiction must be rejected.",
            "candidate assessment line must contain exactly one assessment",
        ),
        (
            "Candidate #225: RELATED — This has a sufficiently long reason. "
            "Candi\u200bdate #225: NOT_RELATED — This hidden contradiction must be rejected.",
            "candidate assessment line must contain exactly one assessment",
        ),
        (
            "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\n"
            "Candi\u200bdate #225: NOT_RELATED — This zero-width assessment must be rejected.",
            "candidate assessment must match the required literal grammar",
        ),
        (
            "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\n"
            "Candi\u034fdate #225: NOT_RELATED — This grapheme-joiner assessment must be rejected.",
            "candidate assessment must match the required literal grammar",
        ),
        (
            "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\n"
            "Candi\ufe0fdate #225: NOT_RELATED — This variation-selector assessment must be rejected.",
            "candidate assessment must match the required literal grammar",
        ),
    )

    for message, expected_error in outputs:
        result = _run_validator(
            tmp_path,
            {"items": [{"type": "noop", "message": message}]},
            duplicate_context=context,
        )

        assert result.returncode == 1
        assert expected_error in result.stderr

    astral_code_points = _run_validator(
        tmp_path,
        {
            "items": [
                {
                    "type": "noop",
                    "message": "Candidate #225: RELATED — a" + ("😀" * 19),
                }
            ]
        },
        duplicate_context=context,
    )
    assert astral_code_points.returncode == 0, astral_code_points.stderr


def test_validator_rejects_syntactic_candidate_mention_and_unused_ack_field(tmp_path: Path):
    context = _trusted_context_with_candidate()
    outputs = (
        {"items": [{"type": "noop", "message": "Color #225 is blue; no action is warranted."}]},
        {
            "items": [
                {
                    "type": "noop",
                    "message": "No public action is warranted.",
                    "ack": "Candidate #225: RELATED — This hidden field must never count.",
                }
            ]
        },
    )

    for output in outputs:
        result = _run_validator(tmp_path, output, duplicate_context=context)

        assert result.returncode == 1
        assert "structured assessment" in result.stderr or "unexpected fields" in result.stderr


def test_validator_requires_uncertainty_and_leaves_free_form_semantics_for_human_review(
    tmp_path: Path,
):
    unsupported = {
        "items": [
            {
                "type": "noop",
                "message": "No related issue exists, so no public action is warranted.",
            }
        ]
    }
    rejected = _run_validator(tmp_path, unsupported)

    assert rejected.returncode == 1
    assert "missing required lexical uncertainty statement" in rejected.stderr

    human_adjudicated_prose = (
        "No duplicate issue was found.",
        "A search of all issues found nothing similar.",
        "No rela\u200bted issue was found.",
        "Nothing sim\u200bilar was found.",
        "A sea\u200brch of all issues found nothing.",
        "No other reports exist.",
        "The search found nothing among existing issues.",
        "The search returned zero matching issues.",
        "I could not find a matching issue.",
        "Repository search returns incorrect results for matching client rules.",
        "Client search returns incorrect candidates for matching rules.",
        "Client search returns no matching candidates because the controller filter is broken.",
        "The issue is matching client rules incorrectly.",
        "Repository search fails to return issues with the requested status.",
    )
    for prose in human_adjudicated_prose:
        result = _run_validator(
            tmp_path,
            {
                "items": [
                    {
                        "type": "noop",
                        "message": NO_CANDIDATE_UNCERTAINTY + "\n" + prose,
                    }
                ]
            },
        )

        assert result.returncode == 0, result.stderr


def test_validator_requires_uncertainty_in_the_narrative_not_a_label_rationale(
    tmp_path: Path,
):
    output = {
        "items": [
            {
                "type": "add_labels",
                "labels": [
                    {
                        "name": "needs-info",
                        "rationale": NO_CANDIDATE_UNCERTAINTY,
                        "confidence": "HIGH",
                    }
                ],
            },
            {
                "type": "add_comment",
                "body": _missing_information_comment("transport"),
            },
        ]
    }

    result = _run_validator(tmp_path, output)

    assert result.returncode == 1
    assert "required lexical uncertainty statement must appear only in narratives" in result.stderr


def test_validator_rejects_uncertainty_caveat_in_label_only_rationale(tmp_path: Path):
    output = {
        "items": [
            {
                "type": "add_labels",
                "labels": [
                    {
                        "name": "enhancement",
                        "rationale": NO_CANDIDATE_UNCERTAINTY,
                        "confidence": "HIGH",
                    }
                ],
            }
        ]
    }

    result = _run_validator(tmp_path, output)

    assert result.returncode == 1
    assert "must appear only in narratives" in result.stderr


def test_validator_rejects_nonmatching_fixed_caveat_in_label_rationale(tmp_path: Path):
    bounded_uncertainty = (
        "Lexical result: No candidate met the threshold in the 1,000 newest issues; "
        "duplicate status remains unknown beyond that bound."
    )
    output = {
        "items": [
            {
                "type": "add_labels",
                "labels": [
                    {
                        "name": "enhancement",
                        "rationale": bounded_uncertainty,
                        "confidence": "HIGH",
                    }
                ],
            }
        ]
    }

    result = _run_validator(tmp_path, output)

    assert result.returncode == 1
    assert "must appear only in narratives" in result.stderr


def test_validator_normalizes_label_caveat_marker_before_exclusion(tmp_path: Path):
    rationales = (
        NO_CANDIDATE_UNCERTAINTY.replace("status", "stat\u200bus"),
        NO_CANDIDATE_UNCERTAINTY.replace(
            "duplicate status remains unknown",
            "Duplicate Status Remains Unknown",
        ),
    )

    for rationale in rationales:
        output = {
            "items": [
                {
                    "type": "add_labels",
                    "labels": [
                        {
                            "name": "enhancement",
                            "rationale": rationale,
                            "confidence": "HIGH",
                        }
                    ],
                }
            ]
        }

        result = _run_validator(tmp_path, output)

        assert result.returncode == 1
        assert "must appear only in narratives" in result.stderr


def test_validator_rejects_label_caveat_duplicating_valid_comment(tmp_path: Path):
    output = {
        "items": [
            {
                "type": "add_labels",
                "labels": [
                    {
                        "name": "enhancement",
                        "rationale": NO_CANDIDATE_UNCERTAINTY,
                        "confidence": "HIGH",
                    }
                ],
            },
            {"type": "add_comment", "body": NO_CANDIDATE_UNCERTAINTY},
        ]
    }

    result = _run_validator(tmp_path, output)

    assert result.returncode == 1
    assert "must appear only in narratives" in result.stderr


def test_validator_requires_exactly_one_uncertainty_statement_per_narrative(tmp_path: Path):
    noop = {
        "items": [
            {
                "type": "noop",
                "message": NO_CANDIDATE_UNCERTAINTY + "\n" + NO_CANDIDATE_UNCERTAINTY,
            }
        ]
    }

    result = _run_validator(tmp_path, noop)

    assert result.returncode == 1
    assert "missing required lexical uncertainty statement" in result.stderr


def test_validator_accepts_bounded_uncertainty_in_narrative_and_trusted_summary(tmp_path: Path):
    context = _trusted_context()
    context.update({"scanned": 1000, "truncated": True})
    bounded_uncertainty = (
        "Lexical result: No candidate met the threshold in the 1,000 newest issues; "
        "duplicate status remains unknown beyond that bound."
    )
    output = {"items": [{"type": "noop", "message": bounded_uncertainty}]}

    result = _run_validator(tmp_path, output, duplicate_context=context)

    assert result.returncode == 0, result.stderr
    assert bounded_uncertainty in (tmp_path / "summary.md").read_text()


def test_validator_accepts_machine_checked_no_distinctive_terms_uncertainty(tmp_path: Path):
    context = _trusted_context()
    context.update(
        {
            "search_performed": False,
            "reason": "no-distinctive-title-terms",
            "scanned": 0,
            "truncated": False,
        }
    )
    output = {
        "items": [
            {
                "type": "noop",
                "message": (
                    "Lexical result: Search skipped because the title had no distinctive terms; "
                    "duplicate status remains unknown."
                ),
            }
        ]
    }

    result = _run_validator(tmp_path, output, duplicate_context=context)

    assert result.returncode == 0, result.stderr
    assert output["items"][0]["message"] in (tmp_path / "summary.md").read_text()


def test_validator_requires_sensitive_stop_for_trusted_sensitive_title_guard(tmp_path: Path):
    context = _trusted_context()
    context.update(
        {
            "search_performed": False,
            "reason": "sensitive-title-guard",
            "scanned": 0,
            "truncated": False,
        }
    )
    uncertainty = {
        "items": [
            {
                "type": "noop",
                "message": (
                    "Lexical result: Search skipped by the sensitive-title guard; duplicate status remains unknown."
                ),
            }
        ]
    }

    rejected = _run_validator(tmp_path, uncertainty, duplicate_context=context)

    assert rejected.returncode == 1
    assert "sensitive title guard requires the exact exclusive noop shape" in rejected.stderr

    accepted = _run_validator(
        tmp_path,
        {"items": [{"type": "noop", "message": "Sensitive intake stop: Maintainer attention is required."}]},
        duplicate_context=context,
    )
    assert accepted.returncode == 0, accepted.stderr
    summary = (tmp_path / "summary.md").read_text()
    assert "Lexical result: Search skipped by the sensitive-title guard" in summary


def test_validator_rejects_issue_reference_outside_trusted_context(tmp_path: Path):
    context = _trusted_context_with_candidate()
    output = {
        "items": [
            {
                "type": "noop",
                "message": (
                    "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\n"
                    "Issue #999 is the better match."
                ),
            }
        ]
    }

    result = _run_validator(tmp_path, output, duplicate_context=context)

    assert result.returncode == 1
    assert "issue reference outside trusted candidate context" in result.stderr


def test_validator_identifies_untrusted_references_from_live_acceptance_output(tmp_path: Path):
    context = _trusted_context_with_candidate(target_number=228)
    output = {
        "items": [
            {
                "type": "noop",
                "message": (
                    "Issue #228 is already closed and resolved by the maintainer.\n\n"
                    "Candidate #225: RELATED — Same root-cause bug was previously fixed "
                    "via merged PR #227/#226."
                ),
            }
        ]
    }

    result = _run_validator(
        tmp_path,
        output,
        duplicate_context=context,
        target_number=228,
    )

    assert result.returncode == 1
    assert "issue reference outside trusted candidate context: #226, #227" in result.stderr


def test_validator_rejects_numbered_pull_request_reference_forms(tmp_path: Path):
    context = _trusted_context_with_candidate(target_number=228)
    for reference in (
        "PR #225",
        "PR 999",
        "PRs 999 and 998",
        "pull request 999",
        "pull requests 999 and 998",
        "pull-request 999",
        "pull-request no. 999",
        "https://github.com/sirkirby/unifi-mcp/pull/999",
        "https://github.com/sirkirby/unifi-mcp/pull/225",
        "sirkirby/unifi-mcp/pull/999",
    ):
        output = {
            "items": [
                {
                    "type": "noop",
                    "message": (
                        "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\n"
                        f"The fix was included in {reference}."
                    ),
                }
            ]
        }

        result = _run_validator(
            tmp_path,
            output,
            duplicate_context=context,
            target_number=228,
        )

        assert result.returncode == 1
        assert "numbered pull-request reference is not allowed" in result.stderr


def test_validator_accepts_number_free_pull_request_paraphrase(tmp_path: Path):
    context = _trusted_context_with_candidate(target_number=228)
    output = {
        "items": [
            {
                "type": "noop",
                "message": (
                    "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\n"
                    "The fix was included in a prior merged change."
                ),
            }
        ]
    }

    result = _run_validator(
        tmp_path,
        output,
        duplicate_context=context,
        target_number=228,
    )

    assert result.returncode == 0, result.stderr


def test_validator_does_not_treat_plural_verb_as_issue_reference(tmp_path: Path):
    context = _trusted_context_with_candidate()
    for prose in (
        "The endpoint issues 500 responses when authentication fails.",
        "The endpoint issues no 500 responses when authentication fails.",
        "The endpoint issues no. 500 responses when authentication fails.",
        "The endpoint issues number 500 responses during the test.",
    ):
        output = {
            "items": [
                {
                    "type": "noop",
                    "message": (
                        "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\n" + prose
                    ),
                }
            ]
        }

        result = _run_validator(tmp_path, output, duplicate_context=context)

        assert result.returncode == 0, result.stderr


def test_validator_rejects_untrusted_explicit_plural_issue_references(tmp_path: Path):
    context = _trusted_context_with_candidate()
    for reference in ("issues #999", "issues: #999"):
        output = {
            "items": [
                {
                    "type": "noop",
                    "message": (
                        "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\n"
                        f"The report also references {reference}."
                    ),
                }
            ]
        }

        result = _run_validator(tmp_path, output, duplicate_context=context)

        assert result.returncode == 1
        assert "issue reference outside trusted candidate context" in result.stderr


def test_validator_rejects_mixed_case_url_and_textual_issue_reference_outside_context(
    tmp_path: Path,
):
    context = _trusted_context_with_candidate()
    for message in (
        "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\n"
        "https://GITHUB.com/sirkirby/unifi-mcp/issues/999 is better.",
        "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\nIssue 999 is better.",
        "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\nIssue: 999 is better.",
        "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\nIssue number 999 is better.",
        "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\nIssue no. 999 is better.",
        "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\nIssue num. 999 is better.",
        "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\n"
        "Iss\u200bue number 999 is better.",
        "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\n"
        "Ｉｓｓｕｅ　ｎｕｍｂｅｒ　９９９ is better.",
        "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\nGH-999 is better.",
        "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\nGH\u200b - 999 is better.",
        "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\n"
        "sirkirby/unifi-mcp#999 is better.",
        "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\n"
        "see:sirkirby/unifi-mcp#999 is better.",
        "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\n"
        "`sirkirby/unifi-mcp#999` is better.",
        "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\n"
        "/sirkirby/unifi-mcp/issues/999 is better.",
        "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\n"
        "github.com/sirkirby/unifi-mcp/issues/999 is better.",
        "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\n"
        "sirkirby/unifi-mcp/issues/999 is better.",
        "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\n"
        "./sirkirby/unifi-mcp/issues/999 is better.",
        "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\n"
        "//github.com/sirkirby/unifi-mcp/issues/999 is better.",
    ):
        output = {"items": [{"type": "noop", "message": message}]}

        result = _run_validator(tmp_path, output, duplicate_context=context)

        assert result.returncode == 1
        assert "issue reference outside trusted candidate context" in result.stderr


def test_validator_rejects_punctuation_adjacent_cross_repository_reference(tmp_path: Path):
    context = _trusted_context_with_candidate()
    for reference in (
        "see:someone/another-repo#225",
        "`someone/another-repo#225`",
        "/someone/another-repo/issues/225",
        "github.com/someone/another-repo/issues/225",
        "someone/another-repo/issues/225",
        "./someone/another-repo/issues/225",
        "//github.com/someone/another-repo/issues/225",
    ):
        output = {
            "items": [
                {
                    "type": "noop",
                    "message": (
                        "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\n"
                        f"{reference} is another match."
                    ),
                }
            ]
        }

        result = _run_validator(tmp_path, output, duplicate_context=context)

        assert result.returncode == 1
        assert "cross-repository reference" in result.stderr


def test_validator_accepts_only_the_exact_sensitive_intake_stop_shape(tmp_path: Path):
    message = "Sensitive intake stop: Maintainer attention is required."
    for context in (_trusted_context(), _trusted_context_with_candidate()):
        accepted = _run_validator(
            tmp_path,
            {"items": [{"type": "noop", "message": message}]},
            duplicate_context=context,
        )
        assert accepted.returncode == 0, accepted.stderr

    rejected = _run_validator(
        tmp_path,
        {
            "items": [
                {"type": "noop", "message": message},
                {
                    "type": "add_labels",
                    "labels": [{"name": "bug", "rationale": "This report requires review.", "confidence": "LOW"}],
                },
            ]
        },
        duplicate_context=_trusted_context_with_candidate(),
    )
    assert rejected.returncode == 1
    assert "sensitive intake stop must use the exact exclusive noop shape" in rejected.stderr

    extended_messages = (
        (
            _trusted_context_with_candidate(),
            message + "\nCandidate #225: RELATED — It reports the same malformed uvx argument failure.",
        ),
        (_trusted_context(), message + "\n" + NO_CANDIDATE_UNCERTAINTY),
    )
    for context, extended_message in extended_messages:
        extended = _run_validator(
            tmp_path,
            {"items": [{"type": "noop", "message": extended_message}]},
            duplicate_context=context,
        )
        assert extended.returncode == 1
        assert "sensitive intake stop must use the exact exclusive noop shape" in extended.stderr


def test_validator_rejects_percent_encoded_issue_url(tmp_path: Path):
    context = _trusted_context_with_candidate()
    output = {
        "items": [
            {
                "type": "noop",
                "message": (
                    "Candidate #225: RELATED — It reports the same malformed uvx argument failure.\n"
                    "https://github.com/sirkirby/unifi-mcp/issues/%39%39%39 is another match."
                ),
            }
        ]
    }

    result = _run_validator(tmp_path, output, duplicate_context=context)

    assert result.returncode == 1
    assert "URL outside the canonical repository" in result.stderr


def test_trusted_research_ranks_issue_225_for_issue_228_and_excludes_target():
    target = {
        "number": 228,
        "title": 'Plugin v0.16.0: args[0] "--python-preference==0.16.0" rejected by uvx, MCP fails to connect',
        "created_at": "2026-05-10T15:00:00Z",
    }
    candidates = [
        {
            "number": 228,
            "title": target["title"],
            "state": "CLOSED",
            "createdAt": "2026-05-10T15:00:00Z",
            "closedAt": "2026-05-10T16:11:02Z",
        },
        {
            "number": 225,
            "title": (
                "unifi-network plugin manifest has malformed uvx args "
                "(--python-preference==0.16.0) — MCP server fails to start"
            ),
            "state": "CLOSED",
            "createdAt": "2026-05-09T20:00:00Z",
            "closedAt": "2026-05-10T01:04:45Z",
        },
        {
            "number": 219,
            "title": "Plugin setup documentation should explain uvx installation",
            "state": "OPEN",
            "createdAt": "2026-05-01T00:00:00Z",
            "closedAt": None,
        },
    ]

    result = _run_research(target=target, candidates=candidates)

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    context = json.loads(output["context"])
    assert [candidate["number"] for candidate in context["candidates"]] == [225]
    assert set(context["candidates"][0]) == {"number", "state", "score"}
    assert context["candidates"][0]["score"] >= 6


def test_trusted_research_follows_graphql_pagination_for_later_candidate():
    target = {
        "number": 228,
        "title": 'Plugin v0.16.0: args[0] "--python-preference==0.16.0" rejected by uvx',
        "created_at": "2026-05-10T15:00:00Z",
    }
    later_candidate = {
        "number": 225,
        "title": "Malformed uvx args (--python-preference==0.16.0)",
        "state": "CLOSED",
        "createdAt": "2026-05-09T20:00:00Z",
        "closedAt": "2026-05-10T01:04:45Z",
    }

    result = _run_research(
        target=target,
        candidates=[],
        candidate_pages=[[], [later_candidate]],
    )

    assert result.returncode == 0, result.stderr
    context = json.loads(json.loads(result.stdout)["context"])
    assert [candidate["number"] for candidate in context["candidates"]] == [225]
    assert context["scanned"] == 1


def test_trusted_research_marks_the_ten_page_scan_bound():
    target = {
        "number": 228,
        "title": "Network client display name is missing",
        "created_at": "2026-05-10T15:00:00Z",
    }
    pages = [
        [
            {
                "number": page * 100 + offset + 1000,
                "title": f"Unrelated report {page}-{offset}",
                "state": "OPEN",
                "createdAt": "2026-05-01T00:00:00Z",
                "closedAt": None,
            }
            for offset in range(100)
        ]
        for page in range(10)
    ]
    pages.append(
        [
            {
                "number": 225,
                "title": "Network client display name is missing",
                "state": "OPEN",
                "createdAt": "2025-01-01T00:00:00Z",
                "closedAt": None,
            }
        ]
    )

    result = _run_research(target=target, candidates=[], candidate_pages=pages)

    assert result.returncode == 0, result.stderr
    context = json.loads(json.loads(result.stdout)["context"])
    assert context["scanned"] == 1000
    assert context["truncated"] is True
    assert context["candidates"] == []


def test_trusted_research_accepts_no_candidates_and_filters_old_closed_issues():
    target = {
        "number": 228,
        "title": "Network client display name is missing",
        "created_at": "2026-05-10T15:00:00Z",
    }
    candidates = [
        {
            "number": 12,
            "title": "Network client display name is missing",
            "state": "CLOSED",
            "createdAt": "2024-01-01T00:00:00Z",
            "closedAt": "2024-01-02T00:00:00Z",
        }
    ]

    result = _run_research(target=target, candidates=candidates)

    assert result.returncode == 0, result.stderr
    context = json.loads(json.loads(result.stdout)["context"])
    assert context["search_performed"] is True
    assert context["candidates"] == []


def test_trusted_research_reports_when_title_has_no_distinctive_terms():
    target = {
        "number": 228,
        "title": "It is a",
        "created_at": "2026-05-10T15:00:00Z",
    }

    result = _run_research(target=target, candidates=[], graphql_error=True)

    assert result.returncode == 0, result.stderr
    context = json.loads(json.loads(result.stdout)["context"])
    assert context["search_performed"] is False
    assert context["reason"] == "no-distinctive-title-terms"


def test_trusted_research_skips_graphql_for_a_sensitive_title():
    target = {
        "number": 228,
        "title": "Leaked token: github_pat_abcdefghijklmnopqrstuvwxyz123456",
        "created_at": "2026-05-10T15:00:00Z",
    }

    result = _run_research(target=target, candidates=[], graphql_error=True)

    assert result.returncode == 0, result.stderr
    context = json.loads(json.loads(result.stdout)["context"])
    assert context["search_performed"] is False
    assert context["reason"] == "sensitive-title-guard"


def test_trusted_research_excludes_sensitive_candidate_titles():
    target = {
        "number": 228,
        "title": "API token authentication failure",
        "created_at": "2026-05-10T15:00:00Z",
    }
    candidates = [
        {
            "number": 225,
            "title": "API token: github_pat_abcdefghijklmnopqrstuvwxyz123456 authentication failure",
            "state": "OPEN",
            "createdAt": "2026-05-09T20:00:00Z",
            "closedAt": None,
        }
    ]

    result = _run_research(target=target, candidates=candidates)

    assert result.returncode == 0, result.stderr
    context = json.loads(json.loads(result.stdout)["context"])
    assert context["candidates"] == []


def test_trusted_research_fails_closed_when_github_candidate_fetch_fails():
    target = {
        "number": 228,
        "title": "Network client display name is missing",
        "created_at": "2026-05-10T15:00:00Z",
    }

    result = _run_research(target=target, candidates=[], graphql_error=True)

    assert result.returncode != 0
    assert "simulated GraphQL failure" in result.stderr


def test_source_and_compiled_output_policy_keep_triage_reviewed_human_only():
    source = WORKFLOW.read_text()
    compiled = LOCK.read_text()
    policy = "Never propose `triage-reviewed`. That completion label is reserved for a human"

    assert policy in source
    config = _compiled_safe_output_config(compiled)
    assert "triage-reviewed" not in config["add_labels"]["allowed"]
    assert "triage-reviewed" in config["add_labels"]["blocked"]


def test_stage_a5_source_and_compiled_policy_keep_only_needs_info_live():
    source = WORKFLOW.read_text()
    compiled = LOCK.read_text()
    config = _compiled_safe_output_config(compiled)

    assert re.search(r"safe-outputs:\n  staged: false\n", source)
    assert config["add_labels"] == {
        "allowed": ["needs-info"],
        "blocked": [
            "triage-reviewed",
            "duplicate",
            "invalid",
            "wontfix",
            "security",
            "good first issue",
            "help wanted",
            "breaking change",
            "compatibility-critical",
            "*[bot]",
        ],
        "issue_intent": True,
        "max": 1,
        "staged": False,
        "target": "${GH_AW_INPUT_ISSUE_NUMBER}",
    }
    assert config["add_comment"]["staged"] is True
    assert "GH_AW_SAFE_OUTPUTS_STAGED" not in compiled

    safe_outputs_job = re.search(
        r"\n  safe_outputs:\n(?P<body>.*?)\n  trusted_duplicate_research:\n",
        compiled,
        re.DOTALL,
    )
    assert safe_outputs_job is not None
    permissions = re.search(
        r"    permissions:\n(?P<body>(?:      .*\n)+?)    concurrency:",
        safe_outputs_job.group("body"),
    )
    assert permissions is not None
    assert permissions.group("body") == "      contents: read\n      issues: write\n"


def test_stage_b_safety_correction_remains_manual_staged_and_read_only():
    source = WORKFLOW.read_text()
    compiled = LOCK.read_text()

    source_triggers = re.search(r"\non:\n(?P<body>.*?)\npermissions:\n", source, re.DOTALL)
    compiled_triggers = re.search(r"\non:\n(?P<body>.*?)\npermissions:\s*\{\}\n", compiled, re.DOTALL)
    assert source_triggers is not None
    assert compiled_triggers is not None
    for trigger_block in (source_triggers.group("body"), compiled_triggers.group("body")):
        assert "workflow_dispatch:" in trigger_block
        assert "pull_request" not in trigger_block
        assert "issues:" not in trigger_block
        assert "schedule:" not in trigger_block

    assert "permissions:\n  contents: read\n  issues: read\n" in source
    assert "threat-detection: false" in source
    assert _compiled_safe_output_config(compiled)["add_comment"]["staged"] is True
    assert "tool-call-limits" not in compiled
    assert "Stage B remains blocked until runtime enforcement exists" in source


def test_runtime_imported_prompt_declares_read_and_disposition_contract():
    source = " ".join(WORKFLOW.read_text().split())

    required_fragments = (
        "First read the target issue with `issue_read(method: get)`.",
        "Otherwise read the target comments with `issue_read(method: get_comments)`",
        "A repeated `get` call does not count as reading comments.",
        "If a required read fails, emit no safe output.",
        "These read requirements are prompt-level Stage A.5 guidance, not validator-attested runtime evidence; "
        "a human must verify the run's tool-use record.",
        "Before calling any safe-output tool, choose exactly one final disposition:",
        "ACTION:** propose `add_labels`, `add_comment`, or both. Never also call `noop`.",
        "NO-ACTION:** propose exactly one `noop`. Never also call `add_labels` or `add_comment`.",
        "A label-only ACTION is complete and does not need a `noop`.",
        "read and evaluate every candidate. Before any safe-output call, verify that the chosen output "
        "includes exactly one sentence for the highest-ranked candidate",
    )

    for fragment in required_fragments:
        assert fragment in source

    compiled = LOCK.read_text()
    assert (
        'GH_AW_PROMPT_CONTENT_0005: "{{#runtime-import .github/workflows/community-issue-triage.md}}\\n"'
    ) in compiled


def test_trusted_duplicate_research_replaces_agent_issue_search():
    source = WORKFLOW.read_text()
    compiled = LOCK.read_text()
    compiled_lines = LOCK.read_text().splitlines()
    manifest_line = next(line for line in compiled_lines if line.startswith("# gh-aw-manifest: "))
    manifest = json.loads(manifest_line.removeprefix("# gh-aw-manifest: "))
    github_server = next(server for server in manifest["mcp_servers"] if server["name"] == "github")

    assert "bounded-title-lexical-v1" in source
    assert "needs.trusted_duplicate_research.outputs.context" in source
    assert "search_issues" not in github_server["tools"]
    assert "github(search_issues)" not in compiled
    assert "candidate.title.length" not in compiled
    assert "title: String(candidate.title" not in compiled
    assert "shared_terms" not in compiled
    assert re.search(r"  activation:\n    needs: trusted_duplicate_research\n", compiled)
    assert re.search(
        r"  safe_outputs:\n    needs:\n(?:      - .*\n)*      - trusted_duplicate_research\n",
        compiled,
    )
    assert "TRUSTED_DUPLICATE_CONTEXT: ${{ needs.trusted_duplicate_research.outputs.context }}" in compiled

    issue_read_limit = re.search(r"- name: issue_read\n(?:\s*#.*\n)?\s*max-calls: (?P<limit>\d+)", source)
    assert issue_read_limit is not None
    assert int(issue_read_limit.group("limit")) == 2 + 5


def test_prompt_requires_minimal_safe_output_argument_shapes():
    source = WORKFLOW.read_text().replace("\n", " ")

    assert "`add_comment` with `{body}`" in source
    assert re.search(
        r"`add_labels` with\s+`\{labels: \[\{name, rationale, confidence\}\]\}`",
        source,
    )
    assert "`noop` with `{message}`" in source
    for forbidden_selector in (
        "item_number",
        "repo",
        "target",
        "comment_id",
        "reply_to_id",
        "suggest",
        "secrecy",
        "integrity",
    ):
        assert forbidden_selector in source


def test_prompt_requires_a_reference_allowlist_preflight_before_safe_output():
    source = " ".join(WORKFLOW.read_text().split())

    assert "Before calling a safe-output tool, scan every free-form output string" in source
    assert "Do not emit any numbered pull-request reference" in source
    assert "a prior merged change" in source
