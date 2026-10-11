#!/usr/bin/env python3
"""Independent plugin SemVer, release pin writebacks, and merge-base admission.

Uses only the standard library so the release workflow and local/PR guard run
exactly the same logic without installing the workspace.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SEMVER = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
)
PACKAGE_PIN = re.compile(r"(unifi-(network|protect|access)-mcp)==(.+)")
MANIFESTS = (".claude-plugin/plugin.json", ".codex-plugin/plugin.json")
MARKETPLACES = (".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json")
PRODUCTS = ("network", "protect", "access")


@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()

    @classmethod
    def parse(cls, value: str) -> Version:
        match = SEMVER.fullmatch(value) if isinstance(value, str) else None
        if not match:
            raise ValueError(f"invalid semver: {value!r}")
        prerelease = tuple(match[4].split(".")) if match[4] else ()
        if any(part.isdigit() and len(part) > 1 and part.startswith("0") for part in prerelease):
            raise ValueError(f"invalid semver prerelease: {value!r}")
        return cls(int(match[1]), int(match[2]), int(match[3]), prerelease)

    @property
    def key(self) -> tuple:
        # Build metadata has no precedence. A stable release sorts after its prereleases.
        suffix = tuple((0, int(p)) if p.isdigit() else (1, p) for p in self.prerelease) or ((2, ""),)
        return self.major, self.minor, self.patch, suffix


def next_version(plugin: str, old_pin: str, new_pin: str) -> str:
    """Map a forward server move onto the plugin's independent version line.

    Before plugin 1.0, breaking changes advance minor and additive changes
    advance patch (the SemVer 0.x convention).
    """
    current, old, new = (Version.parse(v) for v in (plugin, old_pin, new_pin))
    if new.key <= old.key:
        raise ValueError(f"pin must advance: {old_pin} -> {new_pin}")
    if new.major != old.major:
        level = "major"
    elif new.minor != old.minor:
        level = "minor"
    else:
        level = "patch"
    major, minor, patch = current.major, current.minor, current.patch
    if level == "major":
        return f"{major + 1}.0.0" if major else f"0.{minor + 1}.0"
    if level == "minor" and major:
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if result.returncode:
        raise ValueError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def plugin_state(bundle: Path) -> tuple[str, dict[str, str]]:
    versions = [load(bundle / filename).get("version") for filename in MANIFESTS if (bundle / filename).is_file()]
    if not versions:
        raise ValueError(f"{bundle.name}: at least one plugin manifest is required")
    for version in versions:
        Version.parse(version)
    if len(set(versions)) != 1:
        raise ValueError(f"{bundle.name}: manifests disagree: {versions}")
    pins: dict[str, str] = {}
    configs = [bundle / ".mcp.json", bundle / ".mcp.codex.json"]
    if any(path.exists() for path in configs):
        for path in configs:
            found = config_pins(load(path), str(path))
            if path == configs[0]:
                pins = found
            elif found != pins:
                raise ValueError(f"{bundle.name}: mismatched pins between Claude and Codex")
        inline = load(bundle / MANIFESTS[0]) if (bundle / MANIFESTS[0]).exists() else {}
        if "mcpServers" in inline and config_pins(inline, str(bundle / MANIFESTS[0])) != pins:
            raise ValueError(f"{bundle.name}: mismatched pins in inline Claude manifest")
    elif bundle.name != "cross-product":
        raise ValueError(f"{bundle.name}: missing MCP configs")
    return versions[0], pins


def config_pins(data: dict, where: str) -> dict[str, str]:
    servers = data.get("mcpServers", {})
    if not isinstance(servers, dict) or not servers:
        raise ValueError(f"{where}: missing MCP servers")
    pins = {}
    for server in servers.values():
        matches = [m for arg in server.get("args", []) if (m := PACKAGE_PIN.fullmatch(arg))]
        if len(matches) != 1:
            raise ValueError(f"{where}: expected exactly one supported package pin per server")
        package, _, version = matches[0].groups()
        Version.parse(version)
        if package in pins:
            raise ValueError(f"{where}: duplicate package pin {package}")
        pins[package] = version
    return pins


def pin_tag(package: str, version: str) -> str:
    return f"{package.removeprefix('unifi-').removesuffix('-mcp')}/v{version}"


def check(root: Path, base_ref: str, releasing: str | None = None) -> None:
    """Check committed, staged, unstaged and new plugin files against the merge base."""
    base = git(root, "merge-base", "HEAD", base_ref)  # Missing refs must fail, even with no plugin changes.
    changed = set(git(root, "diff", "--name-only", "--no-renames", base, "--", "plugins").splitlines())
    changed.update(git(root, "ls-files", "--others", "--exclude-standard", "--", "plugins").splitlines())
    tags = set(git(root, "tag", "--list").splitlines())
    if releasing:
        tags.add(releasing)
    for filename in MARKETPLACES:
        for entry in load(root / filename).get("plugins", []):
            if "version" in entry:
                raise ValueError(f"{filename}: marketplace entry {entry.get('name')} carries version")
    bundles = {path.name for path in (root / "plugins").iterdir() if path.is_dir()}
    bundles.update(path.split("/")[1] for path in changed if len(path.split("/")) > 2)
    for name in sorted(bundles):
        version, pins = plugin_state(root / "plugins" / name)
        for package, pin in pins.items():
            tag = pin_tag(package, pin)
            if tag not in tags and not (package == "unifi-network-mcp" and f"v{pin}" in tags):
                raise ValueError(f"{name}: pin {package}=={pin} has no release tag ({tag}); fetch tags")
        if not any(path.startswith(f"plugins/{name}/") for path in changed):
            continue
        baseline_files = git(root, "ls-tree", "-r", "--name-only", base, "--", f"plugins/{name}/").splitlines()
        if not baseline_files:  # New plugins have no prior version to exceed.
            continue
        manifest = next((f"plugins/{name}/{m}" for m in MANIFESTS if f"plugins/{name}/{m}" in baseline_files), None)
        if manifest is None:
            raise ValueError(f"{name}: base plugin has no version manifest")
        old = json.loads(git(root, "show", f"{base}:{manifest}"))["version"]
        if Version.parse(version).key <= Version.parse(old).key:
            raise ValueError(f"{name}: changed plugin requires version strictly greater than {old}; got {version}")
    print(f"Plugin versions and release pins pass against merge base {base}")


def update_pin(bundle: Path, new_pin: str) -> bool:
    """Update both client pins and manifest versions; retrying the same pin is a no-op."""
    plugin, pins = plugin_state(bundle)
    package = f"{bundle.name}-mcp"
    if set(pins) != {package}:
        raise ValueError(f"{bundle.name}: expected only {package} pin")
    old_pin = pins[package]
    if new_pin == old_pin:
        return False
    version = next_version(plugin, old_pin, new_pin)
    for filename in (*MANIFESTS, ".mcp.json", ".mcp.codex.json"):
        path = bundle / filename
        if not path.exists() and filename in MANIFESTS:
            continue
        data = load(path)
        if filename in MANIFESTS:
            data["version"] = version
        for server in data.get("mcpServers", {}).values():
            server["args"] = [
                f"{package}=={new_pin}" if arg == f"{package}=={old_pin}" else arg for arg in server["args"]
            ]
        save(path, data)
    print(f"{bundle.name}: plugin {plugin} -> {version}; server {old_pin} -> {new_pin}")
    return True


def latest_tag(tags: set[str], product: str) -> str | None:
    prefix = f"{product}/v"
    candidates = [tag[len(prefix) :] for tag in tags if tag.startswith(prefix)]
    if not candidates and product == "network":
        candidates = [tag[1:] for tag in tags if re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag)]
    versions = [v for v in candidates if SEMVER.fullmatch(v)]
    return max(versions, key=lambda v: Version.parse(v).key) if versions else None


def sync(root: Path, releasing: str | None = None) -> None:
    """Coalesce product tag bursts; core/shared/relay triggers retain their no-op behavior."""
    tags = set(git(root, "tag", "--list").splitlines())
    if releasing:
        tags.add(releasing)
    for product in PRODUCTS:
        version = latest_tag(tags, product)
        if version is None:
            continue
        bundle = root / "plugins" / f"unifi-{product}"
        _, pins = plugin_state(bundle)
        current = pins[f"unifi-{product}-mcp"]
        if Version.parse(version).key < Version.parse(current).key:
            raise ValueError(f"{product}: latest release tag {version} is behind pin {current}")
        update_pin(bundle, version)
        subprocess.run(
            [sys.executable, str(root / "scripts/generate_server_manifest.py"), "--app", product, "--version", version],
            cwd=root,
            check=True,
        )
    check(root, "HEAD", releasing)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "sync"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--base", default="origin/main", help="check against this ref's merge base with HEAD")
    parser.add_argument("--releasing", help="exact package tag being released (allowed before local tag discovery)")
    args = parser.parse_args()
    try:
        if args.command == "check":
            check(args.root, args.base, args.releasing)
        else:
            sync(args.root, args.releasing)
    except (ValueError, OSError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        print(f"Plugin version check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
