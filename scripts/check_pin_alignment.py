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

import shutil
import subprocess
import sys
import tempfile
import venv
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


DOWNSTREAM_PACKAGES: list[Downstream] = [
    Downstream(REPO / "apps/network", "unifi-network-mcp", "unifi_network_mcp.main"),
    Downstream(REPO / "apps/protect", "unifi-protect-mcp", "unifi_protect_mcp.main"),
    Downstream(REPO / "apps/access", "unifi-access-mcp", "unifi_access_mcp.main"),
    Downstream(REPO / "apps/api", "unifi-api-server", "unifi_api"),
    Downstream(
        REPO / "packages/unifi-mcp-relay",
        "unifi-mcp-relay",
        "unifi_mcp_relay.discovery",
    ),
]


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

    return True, "OK"


def main() -> int:
    if shutil.which("uv") is None:
        print("error: `uv` is not on PATH", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="pin-alignment-") as tmp:
        tmp_path = Path(tmp)
        find_links = tmp_path / "wheels"
        find_links.mkdir()

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

        print()
        print("All downstream wheels install and import cleanly with their declared pins.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
