"""Flag two assertion-weakening patterns in test functions changed since a base ref.

usage: python3 weakscan.py <repo> <base-ref> [<head-ref>]   (head defaults to the working tree)

loop-without-length: a `for` over a value whose body asserts, with no `len(...)`
  assertion on that value earlier in the test. An empty result skips every check.
aliased-expected: a mutable value (a parametrized container, or a container the
  test builds itself) passed into a call is later compared with `==` as the
  expected result, without a deepcopy. An in-place change to the input changes
  both sides and still passes.

Exits non-zero when the diff cannot run, so a bad ref never reads as a clean scan.
"""

import ast
import subprocess
import sys


def fail(message):
    """Exit 2: the comparison could not run, which must never read as a clean result."""
    print(message, file=sys.stderr)
    sys.exit(2)


repo, base = sys.argv[1], sys.argv[2]
head = sys.argv[3] if len(sys.argv) > 3 else None


def git(*args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True).stdout


diff_args = [f"{base}...{head}"] if head else [base]
diff = subprocess.run(["git", "diff", "--name-only", *diff_args], cwd=repo, capture_output=True, text=True)
if diff.returncode != 0:
    # A comparison that did not run must not read as a clean scan.
    fail(f"weakscan: git diff {' '.join(diff_args)} failed: {diff.stderr.strip()}")
files = [f for f in diff.stdout.split() if f.split("/")[-1].startswith("test_") and f.endswith(".py")]


def source(path, ref):
    if ref:
        return git("show", f"{ref}:{path}")
    try:
        return open(f"{repo}/{path}").read()
    except OSError:
        return ""


def functions(src):
    out = {}
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out

    def walk(node, prefix):
        for c in ast.iter_child_nodes(node):
            if isinstance(c, ast.ClassDef):
                walk(c, prefix + [c.name])
            elif isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef)) and c.name.startswith("test"):
                out["::".join(prefix + [c.name])] = c

    walk(tree, [])
    return out


def has_assert(nodes):
    return any(isinstance(n, ast.Assert) for stmt in nodes for n in ast.walk(stmt))


def mutable_param(fn, name):
    """True when a parametrize value for name may be a mutable container (dict, list, set or an unknown name)."""
    for dec in fn.decorator_list:
        if not (isinstance(dec, ast.Call) and ast.unparse(dec.func).endswith("parametrize") and len(dec.args) >= 2):
            continue
        argnames = dec.args[0]
        names = (
            [x.strip() for x in argnames.value.split(",")]
            if isinstance(argnames, ast.Constant)
            else [e.value for e in getattr(argnames, "elts", []) if isinstance(e, ast.Constant)]
        )
        if name not in names:
            continue
        idx = names.index(name)
        rows = getattr(dec.args[1], "elts", [])
        for row in rows:
            if isinstance(row, ast.Call) and ast.unparse(row.func).endswith("param"):
                row = ast.Tuple(elts=row.args) if len(names) > 1 else (row.args[0] if row.args else row)
            value = row.elts[idx] if len(names) > 1 and isinstance(row, ast.Tuple) and idx < len(row.elts) else row
            if isinstance(value, (ast.Dict, ast.List, ast.Set, ast.DictComp, ast.ListComp, ast.Name, ast.Starred)) or (
                isinstance(value, ast.Call) and ast.unparse(value.func) in ("dict", "list", "set")
            ):
                return True
            if isinstance(value, ast.Dict) or "{" in ast.unparse(value)[:1] or "[" in ast.unparse(value)[:1]:
                return True
        return False
    return False


CONTAINERS = (ast.Dict, ast.List, ast.Set, ast.DictComp, ast.ListComp, ast.SetComp)


def local_containers(stmts):
    """Names the test binds to a container it builds, plus plain aliases of them."""
    names = set()
    assigns = [n for n in stmts if isinstance(n, ast.Assign) and len(n.targets) == 1]
    for n in sorted(assigns, key=lambda n: n.lineno):
        target, value = n.targets[0], n.value
        if not isinstance(target, ast.Name):
            continue
        built = isinstance(value, CONTAINERS) or (
            isinstance(value, ast.Call) and ast.unparse(value.func) in ("dict", "list", "set")
        )
        if built or (isinstance(value, ast.Name) and value.id in names):
            names.add(target.id)
    return names


def findings(fn):
    found = []
    stmts = list(ast.walk(fn))
    # loop-without-length: only loops over a value the code under test returned
    produced = set()
    for n in stmts:
        value = getattr(n, "value", None)
        if (
            isinstance(n, (ast.Assign, ast.AnnAssign))
            and value is not None
            and any(isinstance(v, (ast.Call, ast.Await)) for v in ast.walk(value))
        ):
            if "deepcopy" in ast.unparse(value):
                continue  # an expected-value snapshot, not a result
            for t in n.targets if isinstance(n, ast.Assign) else [n.target]:
                for sub in ast.walk(t):
                    if isinstance(sub, ast.Name):
                        produced.add(sub.id)
        if isinstance(n, (ast.With, ast.AsyncWith)):
            for item in n.items:
                if isinstance(item.optional_vars, ast.Name):
                    produced.add(item.optional_vars.id)
    for loop in [n for n in stmts if isinstance(n, ast.For)]:
        if not has_assert(loop.body):
            continue
        roots = {x.id for x in ast.walk(loop.iter) if isinstance(x, ast.Name)}
        if not roots & produced:
            continue
        target = ast.unparse(loop.iter)
        guarded = any(
            isinstance(n, ast.Assert)
            and n.lineno < loop.lineno
            and (
                f"len({target})" in ast.unparse(n.test)
                # an equality on a list built from the same value pins its length too
                or any(
                    isinstance(c, ast.ListComp) and any(ast.unparse(g.iter) == target for g in c.generators)
                    for c in ast.walk(n.test)
                )
            )
            for n in stmts
        )
        if not guarded:
            found.append(("loop-without-length", loop.lineno, f"for ... in {target}"))
    # aliased-expected
    names_into_calls = set()
    in_assert = {id(x) for a in stmts if isinstance(a, ast.Assert) for x in ast.walk(a)}
    for call in [n for n in stmts if isinstance(n, ast.Call) and id(n) not in in_assert]:
        for arg in list(call.args) + [k.value for k in call.keywords]:
            for sub in ast.walk(arg):
                if isinstance(sub, ast.Name):
                    names_into_calls.add(sub.id)
    # One level of indirection: a name placed inside a literal that is then passed in.
    for n in stmts:
        if isinstance(n, ast.Assign) and isinstance(n.value, (ast.Dict, ast.List, ast.Tuple)):
            if any(isinstance(t, ast.Name) and t.id in names_into_calls for t in n.targets):
                names_into_calls |= {x.id for x in ast.walk(n.value) if isinstance(x, ast.Name)}
    copied = {
        t.id
        for n in stmts
        if isinstance(n, ast.Assign) and "deepcopy" in ast.unparse(n.value)
        for t in n.targets
        if isinstance(t, ast.Name)
    }
    params = {a.arg for a in fn.args.args if mutable_param(fn, a.arg)} | local_containers(stmts)
    for a in [n for n in stmts if isinstance(n, ast.Assert)]:
        t = a.test
        if isinstance(t, ast.Compare) and any(isinstance(o, ast.Eq) for o in t.ops):
            for side in [t.left, *t.comparators]:
                if (
                    isinstance(side, ast.Name)
                    and side.id in params
                    and side.id in names_into_calls
                    and side.id not in copied
                ):
                    found.append(("aliased-expected", a.lineno, ast.unparse(t)))
    for loop in [n for n in stmts if isinstance(n, ast.For)]:
        roots = {x.id for x in ast.walk(loop.iter) if isinstance(x, ast.Name)}
        hit = roots & params & names_into_calls
        if hit and not hit & copied and has_assert(loop.body):
            found.append(
                ("aliased-expected", loop.lineno, f"expected read from {sorted(hit)[0]} after it was passed in")
            )
    return found


total = 0
for path in files:
    before = functions(source(path, base))
    after = functions(source(path, head))
    for name, fn in after.items():
        old = before.get(name)
        if old is not None and ast.dump(old) == ast.dump(fn):
            continue  # unchanged test
        for kind, line, detail in findings(fn):
            total += 1
            print(f"{kind}\t{path}:{line}\t{name}\t{detail}")
print(f"# {total} finding(s) in {len(files)} changed test file(s)")
