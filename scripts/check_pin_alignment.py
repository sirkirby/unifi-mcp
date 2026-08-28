#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.13"
# dependencies = ["packaging>=26.0"]
# ///
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
4. Assert every built wheel explicitly declares the advisory-safe floors for
   vulnerable transitives exposed at its published install boundary.
5. Preinstall the prior vulnerable workspace resolutions before every wheel,
   then prove its metadata upgrades them to safe versions.
6. Attempt a smoke import of the downstream's runtime entrypoint. If the import
   succeeds, the declared pin permits a working upstream version. If it fails
   with ``ModuleNotFoundError`` (or pip itself fails with no matching version),
   the pin is stale and a fresh PyPI install would crash.
7. Install the Network and API wheels against exactly their declared published
   ``unifi-core`` floors and validate their manager-call contracts. This catches
   newly used Core methods that ordinary imports do not execute.

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

from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import InvalidVersion, Version

REPO = Path(__file__).resolve().parent.parent

UPSTREAM_PACKAGES: dict[str, Path] = {
    "unifi-mcp-shared": REPO / "packages/unifi-mcp-shared",
    "unifi-core": REPO / "packages/unifi-core",
}

MCP_SECURITY_FLOORS: dict[str, str] = {
    "cryptography": "50.0.0",
    "pydantic-settings": "2.14.2",
    "pyjwt": "2.13.0",
    "python-multipart": "0.0.31",
    "starlette": "1.3.1",
    "click": "8.3.3",
}

SECURITY_FLOORS: dict[str, dict[str, str]] = {
    "unifi-core": {"pyjwt": "2.13.0"},
    "unifi-mcp-shared": MCP_SECURITY_FLOORS,
    "unifi-network-mcp": MCP_SECURITY_FLOORS,
    "unifi-protect-mcp": MCP_SECURITY_FLOORS,
    "unifi-access-mcp": MCP_SECURITY_FLOORS,
    "unifi-mcp-relay": MCP_SECURITY_FLOORS,
    "unifi-api-server": {
        "cryptography": "50.0.0",
        "pyjwt": "2.13.0",
        "python-multipart": "0.0.31",
        "starlette": "1.3.1",
        "click": "8.3.3",
    },
}

# These were the vulnerable workspace resolutions before the security update.
# Preinstalling them proves a published wheel upgrades an existing environment,
# rather than merely resolving safely in a fresh environment.
VULNERABLE_BASELINES: dict[str, str] = {
    "cryptography": "49.0.0",
    "pydantic-settings": "2.12.0",
    "pyjwt": "2.12.1",
    "python-multipart": "0.0.27",
    "starlette": "0.50.0",
    "click": "8.3.1",
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
    raise SystemExit("\\n".join(failures))
print(f"validated {len(registry)} catalog bindings against installed Core floor")
"""

_NETWORK_CORE_FLOOR_CONTRACT = """
import ast, json
from importlib.resources import files
from unifi_network_mcp import runtime

root = files("unifi_network_mcp")
manifest = json.loads(root.joinpath("tools_manifest.json").read_text())
manager_instances = {
    name: value
    for name, value in vars(runtime).items()
    if name.endswith("_manager") and not name.startswith("get_")
}
checked = set()
failures = []
for module_name in sorted(set(manifest["module_map"].values())):
    prefix = "unifi_network_mcp."
    if not module_name.startswith(prefix):
        failures.append(f"{module_name}: outside the Network package")
        continue
    relative = module_name.removeprefix(prefix).replace(".", "/") + ".py"
    tree = ast.parse(root.joinpath(relative).read_text(), filename=module_name)
    for node in ast.walk(tree):
        call = node.func if isinstance(node, ast.Call) else None
        if not isinstance(call, ast.Attribute) or not isinstance(call.value, ast.Name):
            continue
        manager_name = call.value.id
        manager = manager_instances.get(manager_name)
        if manager is None:
            continue
        key = (module_name, manager_name, call.attr)
        if key in checked:
            continue
        checked.add(key)
        method = getattr(type(manager), call.attr, None)
        if method is None or not callable(method):
            failures.append(f"{module_name}: missing {manager_name}.{call.attr}")
if not checked:
    failures.append("no direct Core manager call sites were discovered")
if failures:
    raise SystemExit("\\n".join(failures))
print(f"validated {len(checked)} direct Core manager call sites against installed Core floor")
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


def _normalize_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _version_at_least(version: str, floor: str) -> bool:
    return Version(version) >= Version(floor)


def wheel_requirements(wheel: Path) -> list[str]:
    with zipfile.ZipFile(wheel) as archive:
        metadata_name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        metadata = archive.read(metadata_name).decode()
    prefix = "requires-dist:"
    return [line.split(":", 1)[1].strip() for line in metadata.splitlines() if line.lower().startswith(prefix)]


def _requirement_enforces_floor(requirement: Requirement, floor: str, allowed_marker: str | None) -> bool:
    marker = str(requirement.marker) if requirement.marker is not None else None
    if marker != allowed_marker:
        return False

    floor_version = Version(floor)
    for specifier in requirement.specifier:
        if specifier.operator not in {">=", ">", "==", "~="} or "*" in specifier.version:
            continue
        try:
            bound = Version(specifier.version)
        except InvalidVersion:
            continue
        if bound >= floor_version:
            return True
    return False


def check_security_floors(dist_name: str, wheel: Path) -> tuple[bool, str]:
    expected = SECURITY_FLOORS[dist_name]
    declared: dict[str, list[Requirement]] = {}
    invalid: list[str] = []
    for raw_requirement in wheel_requirements(wheel):
        try:
            requirement = Requirement(raw_requirement)
        except InvalidRequirement:
            invalid.append(raw_requirement)
            continue
        name = _normalize_distribution_name(requirement.name)
        declared.setdefault(name, []).append(requirement)

    failures: list[str] = []
    for name, floor in expected.items():
        allowed_marker = 'extra == "protect"' if dist_name == "unifi-core" and name == "pyjwt" else None
        if not any(
            _requirement_enforces_floor(requirement, floor, allowed_marker) for requirement in declared.get(name, [])
        ):
            failures.append(f"{name}>={floor}")

    if invalid:
        return False, "invalid Requires-Dist entries: " + ", ".join(invalid)
    if failures:
        return False, "missing unconditional advisory-safe Requires-Dist floors: " + ", ".join(failures)
    return True, "all advisory-safe Requires-Dist floors are explicit"


def install_security_upgrade(
    dist_name: str,
    install_target: str,
    find_links: Path,
    venv_dir: Path,
) -> tuple[bool, str, Path]:
    venv.create(venv_dir, with_pip=True, clear=True, symlinks=True)
    py = venv_dir / "bin" / "python"
    expected_floors = SECURITY_FLOORS[dist_name]

    try:
        run_capture(
            [
                str(py),
                "-m",
                "pip",
                "install",
                "--quiet",
                "--disable-pip-version-check",
                "--no-deps",
                *(f"{name}=={VULNERABLE_BASELINES[name]}" for name in expected_floors),
            ]
        )
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
                install_target,
            ]
        )
    except subprocess.CalledProcessError as exc:
        return (
            False,
            "pip install failed — the declared dependency metadata cannot upgrade "
            "the vulnerable baseline using PyPI plus workspace-built upstream wheels.\n\n"
            f"{(exc.stderr or '').strip()[-2000:]}",
            py,
        )

    version_script = "\n".join(
        ["from importlib.metadata import version"]
        + [f'print("{name}=" + version("{name}"))' for name in expected_floors]
    )
    installed = run_capture([str(py), "-c", version_script]).stdout.splitlines()
    installed_versions = dict(line.split("=", 1) for line in installed)
    unsafe = [
        f"{name}=={installed_versions[name]} (<{floor})"
        for name, floor in expected_floors.items()
        if not _version_at_least(installed_versions[name], floor)
    ]
    if unsafe:
        return False, "vulnerable packages remained installed: " + ", ".join(unsafe), py
    return True, "vulnerable baseline upgraded to advisory-safe versions", py


def check_downstream(pkg: Downstream, downstream_wheel: Path, find_links: Path, venv_dir: Path) -> tuple[bool, str]:
    upgrade_ok, upgrade_message, py = install_security_upgrade(
        pkg.dist_name,
        str(downstream_wheel),
        find_links,
        venv_dir,
    )
    if not upgrade_ok:
        return False, upgrade_message

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

    return True, upgrade_message


def core_floor_from_wheel(wheel: Path, package_label: str) -> str:
    """Extract a wheel's declared minimum unifi-core version."""
    with zipfile.ZipFile(wheel) as archive:
        metadata_name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        metadata = archive.read(metadata_name).decode()
    requirement = next(
        (line for line in metadata.splitlines() if line.lower().startswith("requires-dist: unifi-core")),
        None,
    )
    if requirement is None:
        raise RuntimeError(f"{package_label} wheel does not declare a unifi-core dependency")
    match = re.search(r">=\s*([0-9]+(?:\.[0-9]+)*)", requirement)
    if match is None:
        raise RuntimeError(f"{package_label} unifi-core dependency has no minimum version: {requirement}")
    return match.group(1)


def api_core_floor_from_wheel(wheel: Path) -> str:
    """Extract the API wheel's declared minimum unifi-core version."""
    return core_floor_from_wheel(wheel, "API")


def network_core_floor_from_wheel(wheel: Path) -> str:
    """Extract the Network wheel's declared minimum unifi-core version."""
    return core_floor_from_wheel(wheel, "Network")


def check_core_floor_contract(
    wheel: Path,
    venv_dir: Path,
    *,
    package_label: str,
    core_extras: str,
    contract: str,
) -> tuple[bool, str]:
    """Install and contract-check a wheel against exactly its published Core floor."""
    floor = core_floor_from_wheel(wheel, package_label)
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
                f"unifi-core[{core_extras}]=={floor}",
                str(wheel),
            ]
        )
        run_capture([str(py), "-m", "pip", "check"])
        result = run_capture([str(py), "-c", contract])
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()[-3000:]
        return (
            False,
            f"Core floor {floor} is unpublished or contract-incompatible.\n{detail}",
        )
    return True, f"Core floor {floor}: {(result.stdout or '').strip()}"


def check_api_core_floor(api_wheel: Path, venv_dir: Path) -> tuple[bool, str]:
    """Install and contract-check the API against exactly its published Core floor."""
    return check_core_floor_contract(
        api_wheel,
        venv_dir,
        package_label="API",
        core_extras="network,protect,access",
        contract=_API_CATALOG_FLOOR_CONTRACT,
    )


def check_network_core_floor(network_wheel: Path, venv_dir: Path) -> tuple[bool, str]:
    """Install and contract-check Network against exactly its published Core floor."""
    return check_core_floor_contract(
        network_wheel,
        venv_dir,
        package_label="Network",
        core_extras="network",
        contract=_NETWORK_CORE_FLOOR_CONTRACT,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    floor_group = parser.add_mutually_exclusive_group()
    floor_group.add_argument(
        "--api-core-floor-only",
        action="store_true",
        help="Verify the API wheel against exactly its published minimum unifi-core version.",
    )
    floor_group.add_argument(
        "--network-core-floor-only",
        action="store_true",
        help="Verify the Network wheel against exactly its published minimum unifi-core version.",
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
        if args.network_core_floor_only:
            network_wheel = build_wheel(REPO / "apps/network", tmp_path / "network")
            ok, message = check_network_core_floor(network_wheel, tmp_path / "network-floor-venv")
            print(("PASS: " if ok else "FAIL: ") + message)
            return 0 if ok else 1

        failures: list[tuple[str, str]] = []
        upstream_wheels: dict[str, Path] = {}
        downstream_wheels: dict[str, Path] = {}
        print("Building upstream wheels (workspace) -> --find-links source")
        for name, path in UPSTREAM_PACKAGES.items():
            wheel = build_wheel(path, find_links)
            upstream_wheels[name] = wheel
            metadata_ok, metadata_msg = check_security_floors(name, wheel)
            print(f"  [{'PASS' if metadata_ok else 'FAIL'}] {name}: {wheel.name} — {metadata_msg}")
            if not metadata_ok:
                failures.append((name, metadata_msg))

        print()
        print("Checking upstream wheels over vulnerable baselines against PyPI")
        upstream_targets = {
            "unifi-mcp-shared": str(upstream_wheels["unifi-mcp-shared"]),
            "unifi-core": f"{upstream_wheels['unifi-core']}[protect]",
        }
        for name, target in upstream_targets.items():
            ok, message, _ = install_security_upgrade(
                name,
                target,
                find_links,
                tmp_path / "venvs" / name,
            )
            print(f"  [{'PASS' if ok else 'FAIL'}] {name} — {message}")
            if not ok:
                failures.append((name, message))

        print()
        print("Checking each downstream wheel over a vulnerable baseline against PyPI")
        for pkg in DOWNSTREAM_PACKAGES:
            wheel = build_wheel(pkg.src, tmp_path / "downstream" / pkg.dist_name)
            downstream_wheels[pkg.dist_name] = wheel
            metadata_ok, metadata_msg = check_security_floors(pkg.dist_name, wheel)
            if not metadata_ok:
                print(f"  [FAIL] {pkg.dist_name} ({wheel.name}) — {metadata_msg}")
                failures.append((pkg.dist_name, metadata_msg))
                continue
            venv_dir = tmp_path / "venvs" / pkg.dist_name
            ok, msg = check_downstream(pkg, wheel, find_links, venv_dir)
            status = "PASS" if ok else "FAIL"
            print(f"  [{status}] {pkg.dist_name} ({wheel.name}) — {metadata_msg}")
            if not ok:
                failures.append((pkg.dist_name, msg))

        if failures:
            print()
            print("=" * 70)
            print("DEPENDENCY METADATA / PIN ALIGNMENT CHECK FAILED")
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

        network_wheel = downstream_wheels["unifi-network-mcp"]
        network_floor_ok, network_floor_message = check_network_core_floor(
            network_wheel, tmp_path / "network-floor-venv"
        )
        print()
        print(f"  [{'PASS' if network_floor_ok else 'FAIL'}] Network tools against published Core floor")
        print(f"  {network_floor_message}")
        if not network_floor_ok:
            return 1

        api_wheel = downstream_wheels["unifi-api-server"]
        floor_ok, floor_message = check_api_core_floor(api_wheel, tmp_path / "api-floor-venv")
        print()
        print(f"  [{'PASS' if floor_ok else 'FAIL'}] API catalog against published Core floor")
        print(f"  {floor_message}")
        if not floor_ok:
            return 1

        print()
        print("All wheels enforce security floors; downstream upgrades, installs, and imports pass.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
