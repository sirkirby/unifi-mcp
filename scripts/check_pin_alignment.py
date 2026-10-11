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
   workspace upstream wheels and ``--index-url`` set to PyPI. Only upstreams
   being released by the change are explicit install targets; other dependencies
   must resolve to published versions allowed by the downstream metadata.
4. Assert every built wheel explicitly declares the advisory-safe floors for
   vulnerable transitives exposed at its published install boundary.
5. Assert deployable Network runtimes exactly pin ``aiounifi`` and ``aiohttp``
   consistently, so a released app version identifies one authentication stack.
6. Preinstall the prior vulnerable workspace resolutions before every wheel,
   then prove its metadata upgrades them to safe versions.
7. Import the downstream's runtime entrypoint, then import every module the
   installed wheel ships (read from the wheel's file list, so directories
   without an ``__init__.py`` are included). Any ``ImportError`` fails: an
   undeclared dependency, or a symbol the PyPI-resolved upstream does not
   provide. Other import-time exceptions are ignored.
8. Install each downstream wheel against exactly its declared published
   ``unifi-core`` floor (and ``unifi-mcp-shared`` floor, where declared; Network
   uses the branch-built shared candidate). Repeat the full module import, and
   resolve every attribute the code reaches through an ``unifi_core`` /
   ``unifi_mcp_shared`` import against that floor, so a newly used upstream
   symbol without a floor bump fails even when the latest upstream has it.
   Network and API additionally validate their manager-call contracts, which
   catches newly used Core methods on instances the attribute scan cannot see.

Exit code 0 on success, 1 on any failure. Diagnostic output is printed to
stdout and is intended to be read directly from the CI log.
"""

from __future__ import annotations

import argparse
import os
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
    "anyio": "4.14.2",
    "cryptography": "50.0.0",
    "pydantic-settings": "2.14.2",
    "pyjwt": "2.15.0",
    "python-multipart": "0.0.31",
    "starlette": "1.3.1",
    "click": "8.3.3",
    "multidict": "6.9.1",
}

SECURITY_FLOORS: dict[str, dict[str, str]] = {
    "unifi-core": {"pyjwt": "2.15.0", "multidict": "6.9.1"},
    "unifi-mcp-shared": MCP_SECURITY_FLOORS,
    "unifi-network-mcp": MCP_SECURITY_FLOORS,
    "unifi-protect-mcp": MCP_SECURITY_FLOORS,
    "unifi-access-mcp": MCP_SECURITY_FLOORS,
    "unifi-mcp-relay": MCP_SECURITY_FLOORS,
    "unifi-api-server": {
        "anyio": "4.14.2",
        "cryptography": "50.0.0",
        "pyjwt": "2.15.0",
        "python-multipart": "0.0.31",
        "starlette": "1.3.1",
        "click": "8.3.3",
        "multidict": "6.9.1",
        "mako": "1.4.2",
    },
}

# Deployable applications must make the Network authentication stack
# reproducible in their wheel metadata. Library packages intentionally retain
# compatibility floors, but uvx/pip users do not consume the workspace lockfile.
REPRODUCIBLE_RUNTIME_PINS: dict[str, tuple[str, ...]] = {
    "unifi-network-mcp": ("aiounifi", "aiohttp"),
    "unifi-api-server": ("aiounifi", "aiohttp"),
}

# These were the vulnerable workspace resolutions before the security update.
# Preinstalling them proves a published wheel upgrades an existing environment,
# rather than merely resolving safely in a fresh environment.
VULNERABLE_BASELINES: dict[str, str] = {
    "anyio": "4.12.0",
    "cryptography": "49.0.0",
    "pydantic-settings": "2.12.0",
    "pyjwt": "2.13.0",
    "python-multipart": "0.0.27",
    "starlette": "0.50.0",
    "click": "8.3.1",
    "multidict": "6.7.0",
    "mako": "1.3.12",
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

# Imports every module an installed distribution ships and reports the ones that
# fail with an ImportError. The module list comes from the distribution's own
# file list (its RECORD), not from pkgutil.walk_packages: walk_packages only
# descends into directories that contain an __init__.py, so a namespace
# subpackage (a directory without one) and every module under it would never be
# imported. An ImportError covers both an undeclared dependency
# (ModuleNotFoundError) and a symbol the installed upstream does not provide
# ("cannot import name"). Other import-time exceptions are not this gate's
# business and are ignored.
_WALK_IMPORTS = """
import importlib, sys
from importlib.metadata import distribution

root = __ROOT__
names = set()
for file in distribution(__DIST__).files or ():
    parts = file.parts
    if not parts or parts[0] != root or file.suffix != ".py":
        continue
    names.add(".".join(parts[:-1] if file.name == "__init__.py" else (*parts[:-1], file.stem)))
if root not in names:
    print("  no modules of {} found in the installed distribution".format(root))
    sys.exit(1)
broken = []
for name in sorted(names):
    try:
        importlib.import_module(name)
    except ModuleNotFoundError as exc:
        broken.append("  {} -> missing dependency: {}".format(name, exc.name))
    except ImportError as exc:
        broken.append("  {} -> {}".format(name, exc))
    except Exception:
        pass
if broken:
    print("\\n".join(broken))
    sys.exit(1)
print("imported {} modules of {}".format(len(names), root))
"""

# Resolves every attribute reached through a name imported from an upstream
# package (`import unifi_core.auth as auth; auth.new_helper`, or
# `from unifi_core.x import Cls; Cls.new_method`) against the installed
# upstream. Import statements already prove the imported names exist; this
# covers the attribute accesses that only fail when the line runs. The scan is
# conservative: a name that is rebound anywhere in the file (assignment,
# parameter, loop target, a second import) is skipped, and resolution stops at
# the first object that is neither a module nor a class.
_UPSTREAM_API_SCAN = """
import ast, importlib, inspect, sys
from importlib.metadata import distribution

UPSTREAM = ("unifi_core", "unifi_mcp_shared")
root = __ROOT__
dist = distribution(__DIST__)


def upstream(module):
    return module in UPSTREAM or module.startswith(tuple(name + "." for name in UPSTREAM))


def load(module):
    try:
        return importlib.import_module(module)
    except Exception:
        return None


def has(obj, attr):
    if hasattr(obj, attr):
        return True
    return inspect.ismodule(obj) and load(obj.__name__ + "." + attr) is not None


def collect(tree):
    bound, ambiguous = {}, set()

    def bind(name, target):
        if name in bound and bound[name] != target:
            ambiguous.add(name)
        bound[name] = target

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not upstream(alias.name):
                    ambiguous.add((alias.asname or alias.name).split(".")[0])
                elif alias.asname:
                    bind(alias.asname, (alias.name, None))
                else:
                    # `import a.b.c` binds `a`; importing the full path is what
                    # makes `a.b.c` reachable as an attribute chain.
                    load(alias.name)
                    bind(alias.name.split(".")[0], (alias.name.split(".")[0], None))
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if node.level == 0 and node.module and upstream(node.module):
                    bind(alias.asname or alias.name, (node.module, alias.name))
                else:
                    ambiguous.add(alias.asname or alias.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            ambiguous.add(node.id)
        elif isinstance(node, ast.arg):
            ambiguous.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            ambiguous.add(node.name)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            ambiguous.add(node.name)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            ambiguous.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            ambiguous.add(node.rest)
    return {name: target for name, target in bound.items() if name not in ambiguous}


def resolve(target):
    module, attr = target
    if attr is None:
        return load(module)
    owner = load(module)
    if owner is None:
        return None
    if hasattr(owner, attr):
        return getattr(owner, attr)
    return load(module + "." + attr)


def chains(tree):
    inner = {id(node.value) for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and id(node) not in inner:
            attrs, base = [], node
            while isinstance(base, ast.Attribute):
                attrs.append(base.attr)
                base = base.value
            if isinstance(base, ast.Name):
                yield node.lineno, base.id, attrs[::-1]


failures, checked = [], 0
for file in dist.files or ():
    if not file.parts or file.parts[0] != root or file.suffix != ".py":
        continue
    tree = ast.parse(dist.locate_file(file).read_text(), filename=str(file))
    names = collect(tree)
    resolved = {}
    for lineno, name, attrs in chains(tree):
        if name not in names:
            continue
        if name not in resolved:
            resolved[name] = resolve(names[name])
        obj = resolved[name]
        path = name
        for attr in attrs:
            if not (inspect.ismodule(obj) or inspect.isclass(obj)):
                break
            checked += 1
            path += "." + attr
            if not has(obj, attr):
                failures.append("  {}:{}: {} is not provided by the installed upstream".format(file, lineno, path))
                break
            obj = getattr(obj, attr) if hasattr(obj, attr) else load(obj.__name__ + "." + attr)
if failures:
    print("\\n".join(sorted(set(failures))))
    sys.exit(1)
print("resolved {} upstream attribute accesses in {}".format(checked, root))
"""


def walk_imports_script(dist_name: str, root_module: str) -> str:
    return _WALK_IMPORTS.replace("__ROOT__", repr(root_module)).replace("__DIST__", repr(dist_name))


def upstream_api_scan_script(dist_name: str, root_module: str) -> str:
    return _UPSTREAM_API_SCAN.replace("__ROOT__", repr(root_module)).replace("__DIST__", repr(dist_name))


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
connection = type("Connection", (), {"unifi_auth": object()})()
traffic_flow_manager = _PRODUCT_BUILDERS["network"]()["traffic_flow_manager"](connection)
if traffic_flow_manager._connection is not connection:
    raise SystemExit("traffic_flow_manager did not retain the API connection manager")
if traffic_flow_manager._dpi_manager._connection is not connection:
    raise SystemExit("traffic_flow_manager DPI provider did not retain the API connection manager")
if traffic_flow_manager._dpi_manager._auth is not connection.unifi_auth:
    raise SystemExit("traffic_flow_manager DPI provider did not retain the API connection auth")
print(f"validated {len(registry)} catalog bindings against installed Core floor")
"""

_NETWORK_CORE_FLOOR_CONTRACT = """
import ast, asyncio, json
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
if runtime.traffic_flow_manager._dpi_manager is not runtime.dpi_manager:
    failures.append("traffic_flow_manager is not wired to the runtime DPI catalogue manager")
async def fake_get_events(*, within, limit, **kwargs):
    if within != 168 or limit != 1000:
        raise AssertionError(f"event catalog sampled within={within}, limit={limit}")
    return [
        {"key": "CLIENT_CONNECTED_WIRELESS_2"},
        {"key": "CLIENT_CONNECTED_WIRELESS_2"},
        {"event": "CLIENT_ROAMED_2"},
    ]
runtime.event_manager.get_events = fake_get_events
catalog = asyncio.run(runtime.event_manager.get_event_types())
expected_catalog = [
    {
        "key": "CLIENT_CONNECTED_WIRELESS_2",
        "prefix": "CLIENT_CONNECTED_WIRELESS_2",
        "description": "Exact event key observed in the 1,000 most recent events within the last 7 days",
        "observed_count": 2,
    },
    {
        "key": "CLIENT_ROAMED_2",
        "prefix": "CLIENT_ROAMED_2",
        "description": "Exact event key observed in the 1,000 most recent events within the last 7 days",
        "observed_count": 1,
    },
]
if catalog != expected_catalog:
    failures.append(f"event_manager.get_event_types returned {catalog!r}")
if failures:
    raise SystemExit("\\n".join(failures))
print(f"validated {len(checked)} direct Core manager call sites against installed Core floor")
"""


def run_capture(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=True, capture_output=True, text=True, **kwargs)


def build_wheel(src: Path, out_dir: Path, *, pretend_version: str | None = None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    if pretend_version is not None:
        env["SETUPTOOLS_SCM_PRETEND_VERSION"] = pretend_version
    run_capture(
        ["uv", "build", "--wheel", str(src), "--out-dir", str(out_dir)],
        env=env,
    )
    wheels = sorted(out_dir.glob("*.whl"), key=lambda p: p.stat().st_mtime)
    if not wheels:
        raise RuntimeError(f"uv build produced no wheel for {src}")
    return wheels[-1]


def wheel_version(wheel: Path) -> Version:
    """Read a wheel's distribution version from its metadata."""
    with zipfile.ZipFile(wheel) as archive:
        metadata_name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        metadata = archive.read(metadata_name).decode()
    raw_version = next(
        line.split(":", 1)[1].strip() for line in metadata.splitlines() if line.lower().startswith("version:")
    )
    return Version(raw_version)


def build_release_candidate_wheel(src: Path, out_dir: Path) -> Path:
    """Build branch code with the exact next stable version it will publish as."""
    development_wheel = build_wheel(src, out_dir)
    development_version = wheel_version(development_wheel)
    if not development_version.is_prerelease and not development_version.is_devrelease:
        return development_wheel

    candidate_version = development_version.base_version
    development_wheel.unlink()
    return build_wheel(src, out_dir, pretend_version=candidate_version)


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


def wheel_dependency_names(wheel: Path) -> set[str]:
    """Return normalized direct dependency names declared by a wheel."""
    names: set[str] = set()
    for raw_requirement in wheel_requirements(wheel):
        try:
            names.add(_normalize_distribution_name(Requirement(raw_requirement).name))
        except InvalidRequirement:
            continue
    return names


def release_candidate_wheels(upstream_wheels: dict[str, Path]) -> tuple[Path, ...]:
    """Return only upstream wheels intentionally published by this release train."""
    shared_wheel = upstream_wheels.get("unifi-mcp-shared")
    return () if shared_wheel is None else (shared_wheel,)


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


def exact_runtime_pins(wheel: Path, names: tuple[str, ...]) -> tuple[bool, dict[str, str], str]:
    """Return exact unconditional runtime pins declared by a wheel."""
    declared: dict[str, list[Requirement]] = {}
    for raw_requirement in wheel_requirements(wheel):
        try:
            requirement = Requirement(raw_requirement)
        except InvalidRequirement:
            continue
        if requirement.marker is None:
            declared.setdefault(_normalize_distribution_name(requirement.name), []).append(requirement)

    pins: dict[str, str] = {}
    failures: list[str] = []
    for raw_name in names:
        name = _normalize_distribution_name(raw_name)
        requirements = declared.get(name, [])
        exact_versions = {
            specifier.version
            for requirement in requirements
            for specifier in requirement.specifier
            if specifier.operator == "==" and "*" not in specifier.version
        }
        if len(requirements) != 1 or len(requirements[0].specifier) != 1 or len(exact_versions) != 1:
            failures.append(f"{name} must have one unconditional exact == pin")
            continue
        version = exact_versions.pop()
        try:
            Version(version)
        except InvalidVersion:
            failures.append(f"{name} has invalid exact pin {version!r}")
            continue
        pins[name] = version

    if failures:
        return False, pins, "; ".join(failures)
    rendered = ", ".join(f"{name}=={version}" for name, version in sorted(pins.items()))
    return True, pins, f"reproducible runtime pins: {rendered}"


def install_security_upgrade(
    dist_name: str,
    install_target: str,
    find_links: Path,
    venv_dir: Path,
    *,
    additional_targets: tuple[str, ...] = (),
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
                *additional_targets,
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


def check_downstream(
    pkg: Downstream,
    downstream_wheel: Path,
    find_links: Path,
    venv_dir: Path,
    upstream_wheels: tuple[Path, ...],
) -> tuple[bool, str]:
    declared_dependencies = wheel_dependency_names(downstream_wheel)
    upgrade_ok, upgrade_message, py = install_security_upgrade(
        pkg.dist_name,
        str(downstream_wheel),
        find_links,
        venv_dir,
        # Passing the branch-built upstream wheels as explicit install targets
        # makes pip validate them against the downstream metadata. Merely
        # exposing prerelease wheels through --find-links lets pip prefer the
        # latest stable PyPI release, which falsely rejects coordinated
        # upstream/downstream dependency migrations.
        additional_targets=tuple(
            str(wheel)
            for wheel in upstream_wheels
            if _normalize_distribution_name(wheel.stem.split("-")[0]) in declared_dependencies
        ),
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
    # alone succeeds. Import every module the wheel ships, including those under
    # directories without an __init__.py, so the whole surface is covered.
    try:
        run_capture([str(py), "-c", walk_imports_script(pkg.dist_name, pkg.root_module)])
    except subprocess.CalledProcessError as exc:
        return False, (
            f"Importing every module of `{pkg.root_module}` failed after install. "
            f"Some module imports a package that is not declared in this package's "
            f"dependencies, or a symbol the resolved upstream does not provide, so a "
            f"fresh PyPI install crashes when that module is first imported.\n\n"
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


def shared_floor_from_wheel(wheel: Path) -> str | None:
    """Extract a wheel's declared minimum unifi-mcp-shared version, if it declares one."""
    for raw_requirement in wheel_requirements(wheel):
        try:
            requirement = Requirement(raw_requirement)
        except InvalidRequirement:
            continue
        if _normalize_distribution_name(requirement.name) != "unifi-mcp-shared" or requirement.marker is not None:
            continue
        for specifier in requirement.specifier:
            if specifier.operator == ">=":
                return specifier.version
    return None


def check_core_floor_contract(
    wheel: Path,
    venv_dir: Path,
    *,
    package_label: str,
    core_extras: str,
    contract: str | None = None,
    additional_targets: tuple[str, ...] = (),
    pkg: Downstream | None = None,
) -> tuple[bool, str]:
    """Install a wheel against exactly its published Core floor and contract-check it.

    When ``pkg`` is given, every module the wheel ships is also imported, and every
    attribute it reaches through an upstream import is resolved, against that floor.
    """
    floor = core_floor_from_wheel(wheel, package_label)
    venv.create(venv_dir, with_pip=True, clear=True, symlinks=True)
    py = venv_dir / "bin" / "python"
    core_target = f"unifi-core[{core_extras}]=={floor}" if core_extras else f"unifi-core=={floor}"
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
                core_target,
                str(wheel),
                *additional_targets,
            ]
        )
        run_capture([str(py), "-m", "pip", "check"])
        scripts = [] if contract is None else [contract]
        if pkg is not None:
            scripts += [
                walk_imports_script(pkg.dist_name, pkg.root_module),
                upstream_api_scan_script(pkg.dist_name, pkg.root_module),
            ]
        results = [run_capture([str(py), "-c", script]).stdout.strip() for script in scripts]
    except subprocess.CalledProcessError as exc:
        detail = (exc.stdout or "").strip()[-2000:] + "\n" + (exc.stderr or "").strip()[-3000:]
        return (
            False,
            f"Core floor {floor} is unpublished or contract-incompatible.\n{detail.strip()}",
        )
    return True, f"Core floor {floor}: " + "; ".join(result for result in results if result)


def _downstream(dist_name: str) -> Downstream:
    return next(pkg for pkg in DOWNSTREAM_PACKAGES if pkg.dist_name == dist_name)


def check_api_core_floor(api_wheel: Path, venv_dir: Path) -> tuple[bool, str]:
    """Install and contract-check the API against exactly its published Core floor."""
    return check_core_floor_contract(
        api_wheel,
        venv_dir,
        package_label="API",
        core_extras="network,protect,access",
        contract=_API_CATALOG_FLOOR_CONTRACT,
        pkg=_downstream("unifi-api-server"),
    )


def check_network_core_floor(
    network_wheel: Path,
    venv_dir: Path,
    *,
    shared_wheel: Path | None = None,
) -> tuple[bool, str]:
    """Install and contract-check Network against exactly its published Core floor."""
    return check_core_floor_contract(
        network_wheel,
        venv_dir,
        package_label="Network",
        core_extras="network",
        contract=_NETWORK_CORE_FLOOR_CONTRACT,
        additional_targets=(() if shared_wheel is None else (str(shared_wheel),)),
        pkg=_downstream("unifi-network-mcp"),
    )


# Downstream packages without a bespoke manager-call contract still get every
# module imported and every upstream attribute access resolved against their
# declared floors. Core extras mirror what each package declares.
FLOOR_ONLY_CORE_EXTRAS: dict[str, str] = {
    "unifi-protect-mcp": "protect",
    "unifi-access-mcp": "access",
    "unifi-mcp-relay": "",
}


def check_floor_only(pkg: Downstream, wheel: Path, venv_dir: Path) -> tuple[bool, str]:
    """Install a wheel against exactly its declared Core and Shared floors and check its upstream use."""
    shared_floor = shared_floor_from_wheel(wheel)
    return check_core_floor_contract(
        wheel,
        venv_dir,
        package_label=pkg.dist_name,
        core_extras=FLOOR_ONLY_CORE_EXTRAS[pkg.dist_name],
        additional_targets=(() if shared_floor is None else (f"unifi-mcp-shared=={shared_floor}",)),
        pkg=pkg,
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
            wheel = (
                build_release_candidate_wheel(path, find_links)
                if name == "unifi-mcp-shared"
                else build_wheel(path, find_links)
            )
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
        candidate_wheels = release_candidate_wheels(upstream_wheels)
        for pkg in DOWNSTREAM_PACKAGES:
            wheel = build_wheel(pkg.src, tmp_path / "downstream" / pkg.dist_name)
            downstream_wheels[pkg.dist_name] = wheel
            metadata_ok, metadata_msg = check_security_floors(pkg.dist_name, wheel)
            if not metadata_ok:
                print(f"  [FAIL] {pkg.dist_name} ({wheel.name}) — {metadata_msg}")
                failures.append((pkg.dist_name, metadata_msg))
                continue
            venv_dir = tmp_path / "venvs" / pkg.dist_name
            ok, msg = check_downstream(
                pkg,
                wheel,
                find_links,
                venv_dir,
                candidate_wheels,
            )
            status = "PASS" if ok else "FAIL"
            print(f"  [{status}] {pkg.dist_name} ({wheel.name}) — {metadata_msg}")
            if not ok:
                failures.append((pkg.dist_name, msg))

        print()
        print("Checking reproducible Network authentication runtime pins")
        runtime_pin_sets: dict[str, dict[str, str]] = {}
        for dist_name, names in REPRODUCIBLE_RUNTIME_PINS.items():
            wheel = downstream_wheels[dist_name]
            ok, pins, message = exact_runtime_pins(wheel, names)
            print(f"  [{'PASS' if ok else 'FAIL'}] {dist_name} — {message}")
            if ok:
                runtime_pin_sets[dist_name] = pins
            else:
                failures.append((dist_name, message))

        if len(runtime_pin_sets) == len(REPRODUCIBLE_RUNTIME_PINS):
            distinct_pin_sets = {tuple(sorted(pins.items())) for pins in runtime_pin_sets.values()}
            if len(distinct_pin_sets) != 1:
                message = "Network and API wheels declare different aiounifi/aiohttp exact pins"
                print(f"  [FAIL] cross-app alignment — {message}")
                failures.append(("network-auth-runtime", message))
            else:
                print("  [PASS] cross-app alignment — Network and API pins match")

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
            network_wheel,
            tmp_path / "network-floor-venv",
            shared_wheel=upstream_wheels["unifi-mcp-shared"],
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
        for dist_name in FLOOR_ONLY_CORE_EXTRAS:
            floor_pkg = _downstream(dist_name)
            floor_ok, floor_message = check_floor_only(
                floor_pkg, downstream_wheels[dist_name], tmp_path / "floor-venvs" / dist_name
            )
            print()
            print(f"  [{'PASS' if floor_ok else 'FAIL'}] {dist_name} against published upstream floors")
            print(f"  {floor_message}")
            if not floor_ok:
                return 1

        print()
        print("All wheels enforce security floors and runtime pins; downstream upgrades, installs, and imports pass.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
