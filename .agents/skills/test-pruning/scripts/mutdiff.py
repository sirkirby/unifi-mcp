"""Does a changed test file still catch every bug the original caught?

Mutates the named source functions with a fixed, generic operator set (delete a
statement, return None/{}/[], return an input argument, drop a keyword argument,
change a string constant, drop a dict key) and runs the original and the changed
test file against each mutant. A mutant the original kills but the changed file
lets through is a lost check. It catches deletions backed by a weaker
replacement; weakscan.py catches loop and aliasing patterns that mutants do not.

usage: python3 mutdiff.py <repo-worktree> <source-file> <function>[,<function>...] <test-file> \
           <original-ref> <changed-ref> [uv run args, default: --package <inferred>]

Run it in a clean worktree: the source and test files are rewritten in place for
each mutant and always restored. It costs a pytest run per mutant (seconds each).
"""

import ast
import subprocess
import sys
from pathlib import Path

repo = Path(sys.argv[1])
source, funcs, test_file, old_ref, new_ref = sys.argv[2], sys.argv[3].split(","), sys.argv[4], sys.argv[5], sys.argv[6]
PACKAGES = {
    "packages/unifi-core/": ["--package", "unifi-core", "--all-extras"],
    "packages/unifi-mcp-shared/": ["--package", "unifi-mcp-shared"],
    "packages/unifi-mcp-relay/": ["--package", "unifi-mcp-relay"],
    "apps/network/": ["--package", "unifi-network-mcp"],
    "apps/protect/": ["--package", "unifi-protect-mcp"],
    "apps/access/": ["--package", "unifi-access-mcp"],
    "apps/api/": ["--package", "unifi-api-server"],
}
pkg = sys.argv[7:] or next(v for k, v in PACKAGES.items() if test_file.startswith(k))


def targets(tree, names):
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]


def collect(tree, names):
    """Every mutation site inside the named functions, in a stable walk order."""
    sites = []
    for fn in targets(tree, names):
        params = [a.arg for a in fn.args.args if a.arg not in ("self", "cls")]
        for node in ast.walk(fn):
            if node is fn:
                continue
            if isinstance(node, ast.stmt) and not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                sites.append(("delete statement", node, None))
            if isinstance(node, ast.Return) and node.value is not None:
                for empty in ("None", "{}", "[]"):
                    sites.append((f"return {empty}", node, empty))
                for p in params:
                    sites.append((f"return input {p}", node, p))
            if isinstance(node, ast.Call):
                for i, kw in enumerate(node.keywords):
                    if kw.arg:
                        sites.append((f"drop keyword {kw.arg}", node, i))
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value.strip()
                and len(node.value) < 200
            ):
                sites.append(("change string", node, None))
            if isinstance(node, ast.Dict):
                for i, k in enumerate(node.keys):
                    if k is not None:
                        sites.append(("drop dict key", node, i))
    return sites


def mutants(src, names):
    """Yield (description, mutated source) for every generic mutation inside the named functions."""
    for index in range(len(collect(ast.parse(src), names))):
        tree = ast.parse(src)
        kind, node, arg = collect(tree, names)[index]
        label = f"{kind} at line {node.lineno}"
        if kind == "delete statement":
            done = False
            for parent in ast.walk(tree):
                for field in ("body", "orelse", "finalbody"):
                    lst = getattr(parent, field, None)
                    if isinstance(lst, list) and node in lst and not done:
                        lst[lst.index(node)] = ast.Pass()
                        done = True
        elif kind.startswith("return input"):
            node.value = ast.Name(id=arg, ctx=ast.Load())
        elif kind.startswith("return"):
            node.value = ast.parse(arg, mode="eval").body
        elif kind.startswith("drop keyword"):
            del node.keywords[arg]
        elif kind == "change string":
            node.value = node.value + "XX"
        elif kind == "drop dict key":
            del node.keys[arg]
            del node.values[arg]
        ast.fix_missing_locations(tree)
        try:
            yield label, ast.unparse(tree)
        except Exception:
            continue


def run_tests():
    r = subprocess.run(
        ["uv", "run", *pkg, "pytest", "-x", "-q", "-p", "no:cacheprovider", test_file],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=300,
    )
    return r.returncode == 0


def show(ref):
    return subprocess.run(
        ["git", "show", f"{ref}:{test_file}"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout


src_path, test_path = repo / source, repo / test_file
original_src, original_test = src_path.read_text(), test_path.read_text()
old_test, new_test = show(old_ref), show(new_ref)
total = killed = 0
lost = []
try:
    for label, mutated in mutants(original_src, funcs):
        total += 1
        src_path.write_text(mutated)
        test_path.write_text(old_test)
        if run_tests():
            continue  # the original tests miss this mutant too
        killed += 1
        test_path.write_text(new_test)
        if run_tests():
            lost.append(label)
finally:
    src_path.write_text(original_src)
    test_path.write_text(original_test)
print(f"{total} mutants, {killed} killed by the original tests, {len(lost)} let through by the changed tests")
for label in lost:
    print("LOST", label)
sys.exit(1 if lost else 0)
