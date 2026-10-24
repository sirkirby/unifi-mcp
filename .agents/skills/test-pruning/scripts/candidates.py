"""List coverage-redundant test functions for one suite.

usage: python3 candidates.py <suite> <baseline-dir> <repo-dir> <out.json> [<exclude-files.txt>]

<suite> is one of core shared relay network protect access api, and
<baseline-dir> holds base.<suite>.coverage for every suite (per-test contexts).

A branch arc this suite covers must stay covered by this suite when it lies in
the suite's own package, or when the package that owns it does not cover it in
its own suite. That matches CI, where each suite reports coverage for its own
package only. A function is a candidate when, after greedily removing the
candidates chosen before it, every arc it must keep is still covered by another
function in the suite. Protected tests and excluded files are never candidates.

A candidate is only coverage-redundant. In the app suites much of the code under
test lives in unifi_core, whose own suite may run it without asserting it, so a
candidate still needs the assertion review in the test-pruning skill.
"""

import ast
import collections
import json
import re
import sqlite3
import sys
from pathlib import Path

suite, base_dir, repo, out = sys.argv[1:5]
ROOTS = {
    "core": "packages/unifi-core",
    "shared": "packages/unifi-mcp-shared",
    "relay": "packages/unifi-mcp-relay",
    "network": "apps/network",
    "protect": "apps/protect",
    "access": "apps/access",
    "api": "apps/api",
}
MODULE_OWNER = {
    "unifi_core": "core",
    "unifi_mcp_shared": "shared",
    "unifi_mcp_relay": "relay",
    "unifi_network_mcp": "network",
    "unifi_protect_mcp": "protect",
    "unifi_access_mcp": "access",
    "unifi_api": "api",
}
PROTECT = re.compile(
    r"redact|secret|credential|auth|permission|policy_gate|gate|secur|token|crypto|api_key|privacy|isolation|drift|"
    r"symmetry|contract|golden|guard|confirm|preview|audit|denied|forbidden|sensitive|leak|ssrf|inject|tls|verify_ssl|"
    r"real_reconnect|incident|evidence|fail_closed|fails_closed|reject|unsafe|mutation_risk|read_only|readonly",
    re.I,
)
# Optional list of test files to leave alone, such as files another open PR changes.
EXCLUDE_FILES = set(Path(sys.argv[5]).read_text().split()) if len(sys.argv) > 5 else set()


def module_path(path):
    """`unifi_core/foo.py` from any absolute source path, or None for non-source files."""
    m = re.search(r"/src/((unifi_[a-z_]+)/.*)$", path)
    return (m.group(1), m.group(2)) if m else (None, None)


def suite_arcs(name):
    """All arcs a suite's baseline covers, keyed by module-relative path."""
    db = sqlite3.connect(f"{base_dir}/base.{name}.coverage")
    paths = dict(db.execute("select id, path from file"))
    return {(module_path(paths[f])[0], a, b) for f, a, b in db.execute("select file_id, fromno, tono from arc")}


owner_cover = {}
db = sqlite3.connect(f"{base_dir}/base.{suite}.coverage")
paths = dict(db.execute("select id, path from file"))
ctx = dict(db.execute("select id, context from context"))
func_arcs = collections.defaultdict(set)
func_items = collections.defaultdict(set)
for fid, cid, a, b in db.execute("select file_id, context_id, fromno, tono from arc"):
    c = ctx[cid]
    if not c:
        continue
    rel, module = module_path(paths[fid])
    if rel is None:
        continue
    owner = MODULE_OWNER.get(module)
    if owner != suite:
        if owner is None:
            continue
        if owner not in owner_cover:
            owner_cover[owner] = suite_arcs(owner)
        if (rel, a, b) in owner_cover[owner]:
            continue  # its own suite keeps it covered
    node = c.rsplit("|", 1)[0]
    func = f"{ROOTS[suite]}/" + re.sub(r"\[.*\]$", "", node)
    func_arcs[func].add((rel, a, b))
    func_items[func].add(node)

# Every test function in the suite's files, with its lines of code, including
# functions that keep no arc (they cover only code other suites own).
loc = {}
for path in sorted(
    {k.split("::", 1)[0] for k in func_arcs}
    | {str(p.relative_to(repo)) for p in Path(repo, ROOTS[suite], "tests").rglob("test_*.py")}
):
    try:
        tree = ast.parse((Path(repo) / path).read_text())
    except (OSError, SyntaxError):
        continue

    def walk(node, prefix, path=path):
        for c in ast.iter_child_nodes(node):
            if isinstance(c, ast.ClassDef):
                walk(c, prefix + [c.name])
            elif isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef)) and c.name.startswith("test"):
                start = min([c.lineno] + [d.lineno for d in c.decorator_list])
                loc["::".join([path] + prefix + [c.name])] = c.end_lineno - start + 1

    walk(tree, [])

for f in loc:
    func_arcs.setdefault(f, set())

count = collections.Counter(a for arcs in func_arcs.values() for a in arcs)
by_arc = collections.defaultdict(set)
for f, arcs in func_arcs.items():
    for a in arcs:
        by_arc[a].add(f)


def protected(f):
    return f.split("::", 1)[0] in EXCLUDE_FILES or bool(PROTECT.search(f))


order = sorted(func_arcs, key=lambda f: (-loc.get(f, 0), len(func_arcs[f]), f))
removed = []
for f in order:
    if protected(f) or f not in loc:
        continue
    if all(count[a] >= 2 for a in func_arcs[f]):
        for a in func_arcs[f]:
            count[a] -= 1
        removed.append(f)
assert all(v >= 1 for v in count.values())
removed_set = set(removed)

result = []
for f in removed:
    overlap = collections.Counter()
    for a in func_arcs[f]:
        for g in by_arc[a]:
            if g != f and g not in removed_set:
                overlap[g] += 1
    n = len(func_arcs[f]) or 1
    result.append(
        {
            "test": f,
            "loc": loc.get(f, 0),
            "cases": len(func_items[f]),
            "kept_arcs": len(func_arcs[f]),
            "kept_overlap": [{"test": g, "share": round(k / n, 2)} for g, k in overlap.most_common(3)],
        }
    )
summary = {
    "suite": suite,
    "functions": len(loc),
    "candidates": len(result),
    "candidate_loc": sum(r["loc"] for r in result),
    "suite_test_fn_loc": sum(loc.values()),
    "candidate_cases": sum(r["cases"] for r in result),
    "candidates_keeping_no_arc": sum(1 for r in result if r["kept_arcs"] == 0),
}
json.dump({"summary": summary, "candidates": result}, open(out, "w"), indent=1)
print(json.dumps(summary))
