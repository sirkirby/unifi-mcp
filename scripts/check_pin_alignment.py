#!/usr/bin/env python3
"""Verify that each downstream wheel's declared pin permits an importable upstream.

The failure this catches
------------------------

Each downstream ``pyproject.toml`` declares a version range for shared upstream
packages (``unifi-mcp-shared``, ``unifi-core``) in ``[project.dependencies]``.
That range becomes the wheel's ``Requires-Dist`` metadata, which is what
``pip``/``uv`` resolves against PyPI on a user's machine.

In the workspace, ``[tool.uv.sources]`` overrides the version range and resolves
to the local checkout. As a result, ``uv lock --check``, ``uv sync``, ``pytest``,
and every CI job pass cleanly even when the declared range excludes the version
of the upstream package that contains code the downstream imports. The bug only
surfaces post-publish, on a fresh ``uvx <pkg>@latest`` install on a user's
machine. Issue #283 was a real instance of this failure mode.

How this script catches it
---------------------------

1. Build a workspace wheel for every upstream and downstream package.
2. For each downstream wheel, create a clean venv with no workspace context.
3. ``pip install`` the downstream wheel with ``--find-links`` pointing at the
   workspace upstream wheels and ``--index-url`` set to PyPI. This is the exact
   resolution path a user hits, except that workspace upstream wheels are
   available as an additional source so coordinated upstream-downstream PRs do
   not falsely fail.
4. Attempt a smoke import of the downstream's runtime entrypoint. If the import
   succeeds, the declared pin permits a working upstream version. If it fails
   with ``ModuleNotFoundError`` (or pip itself fails with no matching version),
   the pin is stale and a fresh PyPI install would crash.

Exit code 0 on success, 1 on any failure. Diagnostic output is printed to
stdout and is intended to be read directly from the CI log.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import venv
import zipfile
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

UPSTREAM_PACKAGES: dict[str, Path] = {
    "unifi-mcp-shared": REPO / "packages/unifi-mcp-shared",
    "unifi-core": REPO / "packages/unifi-core",
}


@dataclass(frozen=True)
class Downstream:
    src: Path
    dist_name: str
    smoke_import: str
    root_module: str


DOWNSTREAM_PACKAGES: list[Downstream] = [
    Downstream(REPO / "apps/network", "unifi-network-mcp", "unifi_network_mcp.main", "unifi_network_mcp"),
    Downstream(REPO / "apps/protect", "unifi-protect-mcp", "unifi_protect_mcp.main", "unifi_protect_mcp"),
    Downstream(REPO / "apps/access", "unifi-access-mcp", "unifi_access_mcp.main", "unifi_access_mcp"),
    Downstream(REPO / "apps/api", "unifi-api-server", "unifi_api", "unifi_api"),
    Downstream(
        REPO / "packages/unifi-mcp-relay",
        "unifi-mcp-relay",
        "unifi_mcp_relay.discovery",
        "unifi_mcp_relay",
    ),
]

# Imports every submodule of a package and reports the ones that fail with a
# missing module. Only ModuleNotFoundError is treated as a failure: that is the
# signature of an undeclared dependency. Other exceptions at import time are a
# different problem and are not this gate's business.
_WALK_IMPORTS = """
import importlib, pkgutil, sys
root = importlib.import_module("{root}")
missing = []
for mod in pkgutil.walk_packages(root.__path__, root.__name__ + "."):
    try:
        importlib.import_module(mod.name)
    except ModuleNotFoundError as exc:
        missing.append((mod.name, exc.name))
    except Exception:
        pass
if missing:
    for mod_name, dep in missing:
        print("  {{}} -> missing dependency: {{}}".format(mod_name, dep))
    sys.exit(1)
"""

_API_CATALOG_FLOOR_CONTRACT = """
import dis, inspect
from unifi_api.services.dispatch_overrides import DISPATCH_ARG_TRANSLATORS
from unifi_api.services.managers import _PRODUCT_BUILDERS
from unifi_api.services.manifest import ManifestRegistry

manager_types = {}
for product, factory in _PRODUCT_BUILDERS.items():
    for manager_attr, builder in factory().items():
        closure = dict(zip(builder.__code__.co_freevars, builder.__closure__ or (), strict=True))
        target_name = next(
            instruction.argval
            for instruction in dis.get_instructions(builder)
            if instruction.opname == "LOAD_DEREF" and instruction.argval in closure
        )
        manager_types[(product, manager_attr)] = closure[target_name].cell_contents

failures = []
registry = ManifestRegistry.load()
for name in registry.all_tools():
    entry = registry.resolve(name)
    manager_type = manager_types[(entry.product, entry.manager_attr)]
    method = getattr(manager_type, entry.manager_method, None)
    if method is None or not callable(method):
        failures.append(f"{name}: missing {entry.manager_attr}.{entry.manager_method}")
        continue
    signature = inspect.signature(method)
    parameters = {key: value for key, value in signature.parameters.items() if key != "self"}
    accepts_kwargs = any(value.kind is inspect.Parameter.VAR_KEYWORD for value in parameters.values())
    accepted = {
        key for key, value in parameters.items()
        if value.kind in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        }
    }
    required = {
        key for key, value in parameters.items()
        if value.default is inspect.Parameter.empty
        and value.kind not in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
    }
    public = set(entry.input_schema.get("properties", {}))
    public_required = set(entry.input_schema.get("required", []))
    translator = DISPATCH_ARG_TRANSLATORS.get(name)
    dispatched = set(translator.manager_parameters) if translator is not None else public
    guaranteed = dispatched if translator is not None else public_required
    unexpected = set() if accepts_kwargs else dispatched - accepted
    missing = required - guaranteed
    if unexpected or missing:
        failures.append(
            f"{name}: {entry.manager_attr}.{entry.manager_method} "
            f"unexpected={sorted(unexpected)} missing={sorted(missing)}"
        )
if failures:
    raise SystemExit("\n".join(failures))
print(f"validated {len(registry)} catalog bindings against installed Core floor")
"""


def run_capture(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=True, capture_output=True, text=True, **kwargs)


def build_wheel(src: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    run_capture(["uv", "build", "--wheel", str(src), "--out-dir", str(out_dir)])
    wheels = sorted(out_dir.glob("*.whl"), key=lambda p: p.stat().st_mtime)
    if not wheels:
        raise RuntimeError(f"uv build produced no wheel for {src}")
    return wheels[-1]


def check_downstream(pkg: Downstream, downstream_wheel: Path, find_links: Path, venv_dir: Path) -> tuple[bool, str]:
    venv.create(venv_dir, with_pip=True, clear=True, symlinks=True)
    py = venv_dir / "bin" / "python"

    try:
        run_capture(
            [
                str(py),
                "-m",
                "pip",
                "install",
                "--quiet",
                "--disable-pip-version-check",
                "--find-links",
                str(find_links),
                "--index-url",
                "https://pypi.org/simple",
                str(downstream_wheel),
            ]
        )
    except subprocess.CalledProcessError as exc:
        return False, (
            "pip install failed — the declared pin range cannot be satisfied by "
            "PyPI plus workspace-built upstream wheels.\n\n"
            f"{(exc.stderr or '').strip()[-2000:]}"
        )

    try:
        run_capture([str(py), "-c", f"import {pkg.smoke_import}"])
    except subprocess.CalledProcessError as exc:
        return False, (
            f"`import {pkg.smoke_import}` failed after install. The declared pin "
            f"resolved to an upstream version that does not contain the imported "
            f"code path.\n\n"
            f"{(exc.stderr or '').strip()[-2000:]}"
        )

    # Importing one entrypoint only proves that module's imports resolve. An
    # undeclared dependency used anywhere else in the package stays invisible:
    # unifi-api-server shipped for three releases importing unifi_mcp_shared
    # from services/manifest.py without declaring it, because `import unifi_api`
    # alone succeeds. Walk every submodule so the whole surface is covered.
    try:
        run_capture([str(py), "-c", _WALK_IMPORTS.format(root=pkg.root_module)])
    except subprocess.CalledProcessError as exc:
        return False, (
            f"Importing every submodule of `{pkg.root_module}` failed after install. "
            f"Some module imports a package that is not declared in this package's "
            f"dependencies, so a fresh PyPI install crashes when that module is "
            f"first imported.\n\n"
            f"{(exc.stdout or '').strip()[-2000:]}\n{(exc.stderr or '').strip()[-1000:]}"
        )

    return True, "OK"


def api_core_floor_from_wheel(wheel: Path) -> str:
    """Extract the API wheel's declared minimum unifi-core version."""
    with zipfile.ZipFile(wheel) as archive:
        metadata_name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        metadata = archive.read(metadata_name).decode()
    requirement = next(
        (line for line in metadata.splitlines() if line.lower().startswith("requires-dist: unifi-core")),
        None,
    )
    if requirement is None:
        raise RuntimeError("API wheel does not declare a unifi-core dependency")
    match = re.search(r">=\s*([0-9]+(?:\.[0-9]+)*)", requirement)
    if match is None:
        raise RuntimeError(f"API unifi-core dependency has no minimum version: {requirement}")
    return match.group(1)


def check_api_core_floor(api_wheel: Path, venv_dir: Path) -> tuple[bool, str]:
    """Install and contract-check the API against exactly its published Core floor."""
    floor = api_core_floor_from_wheel(api_wheel)
    venv.create(venv_dir, with_pip=True, clear=True, symlinks=True)
    py = venv_dir / "bin" / "python"
    try:
        run_capture(
            [
                str(py),
                "-m",
                "pip",
                "install",
                "--quiet",
                "--disable-pip-version-check",
                "--index-url",
                "https://pypi.org/simple",
                f"unifi-core[network,protect,access]=={floor}",
                str(api_wheel),
            ]
        )
        run_capture([str(py), "-m", "pip", "check"])
        result = run_capture([str(py), "-c", _API_CATALOG_FLOOR_CONTRACT])
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()[-3000:]
        return (
            False,
            f"Core floor {floor} is unpublished or contract-incompatible.\n{detail}",
        )
    return True, f"Core floor {floor}: {(result.stdout or '').strip()}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-core-floor-only",
        action="store_true",
        help="Verify the API wheel against exactly its published minimum unifi-core version.",
    )
    args = parser.parse_args()
    if shutil.which("uv") is None:
        print("error: `uv` is not on PATH", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="pin-alignment-") as tmp:
        tmp_path = Path(tmp)
        find_links = tmp_path / "wheels"
        find_links.mkdir()

        if args.api_core_floor_only:
            api_wheel = build_wheel(REPO / "apps/api", tmp_path / "api")
            ok, message = check_api_core_floor(api_wheel, tmp_path / "api-floor-venv")
            print(("PASS: " if ok else "FAIL: ") + message)
            return 0 if ok else 1

        print("Building upstream wheels (workspace) -> --find-links source")
        for name, path in UPSTREAM_PACKAGES.items():
            wheel = build_wheel(path, find_links)
            print(f"  {name}: {wheel.name}")

        print()
        print("Checking each downstream wheel in a clean venv against PyPI")
        failures: list[tuple[str, str]] = []
        for pkg in DOWNSTREAM_PACKAGES:
            wheel = build_wheel(pkg.src, tmp_path / "downstream" / pkg.dist_name)
            venv_dir = tmp_path / "venvs" / pkg.dist_name
            ok, msg = check_downstream(pkg, wheel, find_links, venv_dir)
            status = "PASS" if ok else "FAIL"
            print(f"  [{status}] {pkg.dist_name} ({wheel.name})")
            if not ok:
                failures.append((pkg.dist_name, msg))

        if failures:
            print()
            print("=" * 70)
            print("PIN ALIGNMENT CHECK FAILED")
            print("=" * 70)
            for name, msg in failures:
                print()
                print(f"--- {name} ---")
                print(msg)
            print()
            print(
                "Why this matters: workspace `[tool.uv.sources]` overrides the "
                "version range in `[project.dependencies]`, so this failure is "
                "invisible to `uv lock --check`, `uv sync`, and every "
                "workspace-based test job. The pin only takes effect in the "
                "wheel's `Requires-Dist` metadata — i.e., on a user's machine "
                "running `uvx <pkg>@latest` or `pip install <pkg>`."
            )
            print()
            print(
                "Two failure shapes are common:\n"
                "  • Stale pin: an existing pin's upper bound excludes the "
                "upstream version that contains code the downstream now imports. "
                "Fix by widening the upper bound in the failing downstream's "
                "`pyproject.toml` (e.g., `unifi-mcp-shared>=0.5.0,<0.6`).\n"
                "  • Premature pin bump: a downstream now requires an upstream "
                "version that has not been published to PyPI yet. Split the "
                "change: merge and release the upstream first, then open a "
                "follow-up PR that bumps the downstream pin and adds the imports."
            )
            print()
            print(
                "See `.agents/skills/monorepo-release-pipeline/SKILL.md` "
                "Procedure D for the manual wheel-metadata check this CI gate "
                "automates."
            )
            return 1

        api_wheel = build_wheel(REPO / "apps/api", tmp_path / "api-floor")
        floor_ok, floor_message = check_api_core_floor(api_wheel, tmp_path / "api-floor-venv")
        print()
        print(f"  [{'PASS' if floor_ok else 'FAIL'}] API catalog against published Core floor")
        print(f"  {floor_message}")
        if not floor_ok:
            return 1

        print()
        print("All downstream wheels install and import cleanly with their declared pins.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
